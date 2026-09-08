"""ProbeContext — 探测工具面的共享状态与红线设施单点。

安全红线（与组装壳 server.py 的对外承诺一致）：
- **host 边界 + 凭证外发硬门禁**：仅可访问「用户提供的 host + 用户经 ask_user
  确认过的 host」；凭证只发往确认过的 host，且按 (host, ref) 组合首次外发前
  经用户授权一次（预览确认即凭证外发同意），每次外发留痕；
- **探测内容注入防护**：抓回内容一律视为 data——分隔包裹 + 截断 + 数据非指令
  声明，最终防线是 staging→diff→用户确认；
- **凭证请求防锁**：同一（ref, url, body）组合被认证层拒绝（4xx/5xx）后不再
  自动重发（防真实系统撞锁）；2xx 组合不入锁——declare_token 事后声明/修正
  提取不重发请求；
- **总量约束**：单探测 10s 超时、轮内预算按工具分池、发现阶梯路径清单 ≤10。

状态全部公开名（各域工具类经 ``ctx`` 跨模块协作——下划线私有名跨模块引用是
反模式）；唯 ``_client_instance`` 为懒建句柄私有。
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from agent_eval.agent.workbench.sut_probe.helpers import host_of
from agent_eval.agent.workbench.sut_probe.specs import PROBE_TIMEOUT_S, TOOL_BUDGETS

# 抓取缓存（前端包分析原语的存储侧）：完整内容只进缓存不进 LLM 上下文，
# 检索摘录按需取回——1.7MB 级前端主包因此可分析而不爆上下文
_MAX_CACHE_FILE = 3_000_000
_MAX_CACHED_FILES = 8


class ProbeContext:
    """探测会话共享状态：host 门禁 / 轮内预算 / 抓取缓存 / 证据账本 / 共享 client。"""

    def __init__(
        self,
        *,
        allowed_hosts: set[str] | None = None,
        ask_fn: Any = None,  # async (question, *, options, secret) -> str | None
        credential_store: Any = None,  # CredentialStore
        log_path: Path | None = None,
        http_client_factory: Any = None,
        budgets: dict[str, int] | None = None,  # 轮内预算按工具分池（缺省 TOOL_BUDGETS）
        timeout_s: float = PROBE_TIMEOUT_S,
    ) -> None:
        self.allowed_hosts = {h.lower() for h in (allowed_hosts or {})}
        # 拒绝拉黑账本（与 workbench_tools._ensure_grant 的 _denied 同款）：被拒
        # host 不再反复弹授权确认（同一授权模式两处实现行为必须一致）
        self.denied_hosts: set[str] = set()
        self.ask_fn = ask_fn
        self.credential_store = credential_store
        self.log_path = log_path
        self.http_client_factory = http_client_factory
        self.budgets = dict(budgets) if budgets is not None else dict(TOOL_BUDGETS)
        self.timeout_s = timeout_s
        self.turn_calls: dict[str, int] = {}
        # 抓取缓存（url → 完整内容）：前端包分析的存储侧，会话内跨轮有效
        # （预算按轮重置但分析状态不丢——新轮可直接检索续查）
        self.fetched: dict[str, str] = {}
        # 防锁：同 (ref, url, body) 凭证请求组合被认证层拒绝（4xx/5xx）即入锁——
        # 配置未变不重试；用户纠正字段/接口后模板变化视为新组合，允许再次实测；
        # 2xx 组合不入锁（declare_token 事后声明/修正提取不重发请求）
        self.login_tried: set[tuple[str, str, str]] = set()
        # 证据账本（落盘对账门禁的事实源）：探测工具在验证成功时把事实**机械登记**
        # 于此（不经 LLM 转述），提交门禁用执行器同款解析逻辑与暂存 sut_configs
        # 逐字段对账——验证结论到落盘配置的传递「原样即可、变形必被打回」
        self.verified_logins: dict[str, dict[str, str]] = {}  # ref(小写) → 实测事实
        self.verified_protocols: dict[str, dict[str, Any]] = {}  # host → 矩阵事实
        # 会话凭证服务端持有：ref(小写) → {token, source}——已声明的凭证按 source
        # 自动挂载（与执行器 mount_headers 三态同构，cookie 型由共享 client 的
        # cookie jar 承载）；值不出现在任何工具返回里，不回流 LLM 上下文
        self.session_tokens: dict[str, dict[str, str]] = {}
        # 凭证外发授权账本：(host, ref小写) 组合级——首次外发前经用户确认一次，
        # 同组合后续外发不再逐次打扰（每次外发仍留痕审计）
        self.credential_grants: set[tuple[str, str]] = set()
        # 最近一次带凭证请求的事实（ref → 原始模板/状态/响应/cookie 名值对）：
        # declare_token 事后声明式提取的唯一事实源（提取在此数据上进行，
        # 不重发请求）；值全部服务端保管
        self.last_credential_request: dict[str, dict[str, Any]] = {}
        # 链式认证步骤：步骤名 → 该步响应 JSON——后续 request 的模板变量
        # {{ stepN.路径 }} 引用其值（值服务端流动，不经对话）
        self.step_responses: dict[str, Any] = {}
        # 会话级共享 AsyncClient（与执行器 channels/base.py 同构：连接池 +
        # cookie jar——cookie 型凭证与会话粘性靠它），会话结束 aclose()
        self._client_instance: Any = None

    # ── 会话挂点与日志 ────────────────────────────────────────────

    def new_turn(self) -> None:
        """每轮 REPL 开始时由 WorkbenchAgent 调用：重置各工具轮内预算。

        抓取缓存**跨轮保留**（会话内有效，容量有界）——预算报错指引「用户回复
        任意消息开启新一轮后继续验证」，若连缓存一起清空，新轮先要把前端主包
        重抓重搜才能回到原地，放大的预算也会先耗在重复劳动上。
        """
        self.turn_calls.clear()

    def log(self, tool: str, **payload: Any) -> None:
        if self.log_path is None:
            return
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        entry = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "tool": tool, **payload}
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")

    # ── 证据账本（门禁对账的事实源：登记/查询收口在此） ──────────

    def record_login(self, fact: dict[str, str]) -> None:
        """登录实测成功 → 登记账本（同 ref 取最新一次成功）。"""
        self.verified_logins[fact["ref"].lower()] = fact
        self.log("login_verified", ref=fact["ref"], url=fact["url"])

    def record_protocol(self, host: str, flavor: str, steps: dict[str, bool]) -> None:
        """协议矩阵实测 → 协议账本（含失败矩阵——「探测过但未支持」也是事实）。"""
        self.verified_protocols[host.lower()] = {"flavor": flavor, "steps": steps}
        self.log("protocol_probed", host=host, flavor=flavor, steps=steps)

    def verified_login(self, ref: str) -> dict[str, str] | None:
        """查登录实测事实（落盘对账门禁用）。"""
        return self.verified_logins.get(ref.lower())

    def verified_protocol(self, host: str) -> dict[str, Any] | None:
        """查协议矩阵事实（落盘对账门禁用）。"""
        return self.verified_protocols.get(host.lower())

    @property
    def login_hosts(self) -> set[str]:
        """本会话登录实测成功过的接口域（小写）——协议探测的候选证据源。"""
        hosts: set[str] = set()
        for fact in self.verified_logins.values():
            if host := host_of(fact.get("url", "")):
                hosts.add(host.lower())
        return hosts

    @property
    def protocol_hosts(self) -> set[str]:
        """已实测过协议矩阵的 host（小写）——证据账本的 host 集合视图。"""
        return set(self.verified_protocols)

    def store_token(self, ref: str, token: str, source: str = "bearer") -> None:
        """声明提取的会话凭证服务端持有（仅内部使用，不进任何返回值）。"""
        self.session_tokens[ref.lower()] = {"token": token, "source": source}

    @property
    def auth_headers(self) -> dict[str, str]:
        """已声明会话凭证的自动挂载头（与执行器 mount_headers 三态同构，无则空）。

        bearer → Authorization: Bearer；header:X → 自定义头；cookie → 空字典
        （cookie 由共享 client 的 cookie jar 承载，declare_token 落 jar）。
        """
        if not self.session_tokens:
            return {}
        entry = list(self.session_tokens.values())[-1]
        source = entry.get("source", "bearer")
        if source == "cookie":
            return {}
        if source.startswith("header:"):
            return {source[len("header:") :]: entry["token"]}
        return {"Authorization": f"Bearer {entry['token']}"}

    # ── 红线设施：轮内预算 / host 边界 ───────────────────────────

    def budget(self, tool: str) -> dict[str, str] | None:
        limit = self.budgets.get(tool)
        if limit is None:
            return None
        self.turn_calls[tool] = self.turn_calls.get(tool, 0) + 1
        if self.turn_calls[tool] > limit:
            self.log(tool, event="budget_exceeded")
            # 达上限 ≠ 收尾信号：指引继续验证而非把未验证猜测写进配置
            return {
                "error": (
                    f"本轮 {tool} 调用已达上限（{limit}）。请把已有证据如实呈现给用户并询问"
                    f"下一步——可请用户回复任意消息开启新一轮（探测预算按轮重置）后继续验证；"
                    f"未经验证的接口/字段不得当作结论写入 sut_configs"
                )
            }
        return None

    def host_gate(self, url: str) -> str | None:
        host = host_of(url)
        if not host:
            return f"无法解析 host: {url}"
        host = host.lower()
        if host in self.denied_hosts:
            return f"该 host 此前已被用户拒绝，勿再试探: {host}——请与用户确认正确的地址"
        if host not in self.allowed_hosts:
            return (
                f"host {host} 未获用户授权（红线：仅可访问用户提供或确认过的 host）。"
                f"请先 ask_user 征得用户对该 host 的确认后再试"
            )
        return None

    async def ensure_host(self, url: str) -> str | None:
        """host 边界：未授权 host 经 ask_user 征得用户同意后放行。"""
        err = self.host_gate(url)
        if err is None:
            return None
        host = host_of(url)
        if host.lower() in self.denied_hosts:
            return err  # 拉黑账本命中：直接返回，不再重复打扰用户
        if self.ask_fn is None:
            return err
        answer = await self.ask_fn(
            f"是否允许探测工具访问 {host}？（SUT 接入调试需要）",
            options=["允许", "不允许"],
            secret=False,
        )
        if answer and "允许" in answer and "不允许" not in answer:
            self.allowed_hosts.add(host.lower())
            self.log("host_authorized", host=host)
            return None
        self.denied_hosts.add(host.lower())
        self.log("host_denied", host=host)
        return f"用户拒绝访问 {host}，不得探测该 host；请与用户确认正确的地址"

    # ── 抓取缓存原语（request(GET) / discover_login 的存储侧） ───

    def cache_content(self, url: str, content: str) -> None:
        """完整内容入缓存（单文件截断 + 条目数上限，淘汰最早抓取的）。"""
        if len(content) > _MAX_CACHE_FILE:
            content = content[:_MAX_CACHE_FILE] + "\n…（超长，仅缓存前段）"
        if len(self.fetched) >= _MAX_CACHED_FILES:
            self.fetched.pop(next(iter(self.fetched)))
        self.fetched[url] = content

    async def fetch_text(self, url: str) -> tuple[str | None, str]:
        """抓取文本，返回（内容, 失败原因）——失败原因必须保留（DNS/超时/证书
        各不相同，吞成一句「不可达」会让 Agent 与用户失去自诊断依据）。"""
        try:
            client = await self.client()
            response = await client.get(url)
            return str(response.text), ""
        except Exception as e:  # noqa: BLE001 — 失败原因交调用方呈现与决策
            return None, str(e)[:200]

    # ── 会话级共享 client ────────────────────────────────────────

    async def client(self) -> Any:
        """会话级共享 AsyncClient（懒建）：连接池复用 + cookie jar 跨请求保持。

        与执行器通道同构（channels/base.py）：登录态 cookie、会话粘性都靠共享
        client 的 jar——每请求新建 client 丢 cookie 的宽度裂缝在此消灭。
        会话结束经 aclose() 释放。
        """
        if self._client_instance is None:
            if self.http_client_factory is not None:
                self._client_instance = self.http_client_factory()
            else:
                import httpx

                self._client_instance = httpx.AsyncClient(
                    timeout=self.timeout_s, follow_redirects=False
                )
        return self._client_instance

    def borrow_client(self) -> Any:
        """``async with`` 形态借用共享 client（退出时不关闭——归会话统一释放）。

        供多请求长块（协议矩阵/页面发现）沿用 ``async with client_cm`` 缩进，
        语义从「with 即关闭」变为「with 即借用」。
        """
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def _cm() -> Any:
            yield await self.client()

        return _cm()

    async def aclose(self) -> None:
        """释放共享 client（会话结束/Agent 关停时调用；幂等）。"""
        if self._client_instance is not None:
            try:
                await self._client_instance.aclose()
            except Exception:  # noqa: BLE001 — 释放失败不阻断收尾
                pass
            self._client_instance = None
