"""SUTProbeToolServer — SUT 接入调试受控网络工具面的组装壳（arch/15 §6.6/§6.11.2）。

与文件沙盒（workbench_tools，无网络不变式）并列的独立 server：创建场景包时由
Agent 主动探测被测系统（地址可达性 / agent-protocol 符合性 / 登录 API 发现与
实测），**验证过的结论才经 staging 门禁写进 sut_configs/**。实现按域拆分在
同包 mixin（fetch/discovery/protocol/login），本壳持有共享状态与红线设施——
「一域一 server」形态不变（D-WB-7），拆的是实现不是边界。

安全红线（arch/15 §6.6 评审定稿；v4 探测面 docs/plan/03）：
- **host 边界 + 凭证外发硬门禁**：仅可访问「用户提供的 host + 用户经 ask_user
  确认过的 host」；凭证只发往确认过的 host，且按 (host, ref) 组合首次外发前
  经用户授权一次（预览确认即凭证外发同意），每次外发留痕；
- **探测内容注入防护**：抓回内容一律视为 data——分隔包裹 + 截断 + 数据非指令
  声明，最终防线是 staging→diff→用户确认；
- **凭证请求防锁**：同一（ref, url, body）组合被认证层拒绝（4xx/5xx）后不再
  自动重发（防真实系统撞锁）；2xx 组合不入锁——declare_token 事后声明/修正
  提取不重发请求；
- **总量约束**：单探测 10s 超时、轮内预算按工具分池、发现阶梯路径清单 ≤10。

ask_user 桥接 CLI 交互原语（文本/单选/凭证隐藏输入直写 secrets，值不回流 LLM
上下文）；非交互（``--yes`` CI）形态 ask_fn 为空 → 返回「需交互」错误。
工具异常以 ``{"error": ...}`` 返回交 Agent 自修复（tool_guard 精神）。
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, ClassVar

from agent_eval.agent.probe.discovery import DiscoveryMixin
from agent_eval.agent.probe.fetch import FetchMixin, _host_of
from agent_eval.agent.probe.login import LoginMixin
from agent_eval.agent.probe.protocol import ProtocolMixin
from agent_eval.agent.tools import ToolExporterMixin, ToolSpec

PROBE_TIMEOUT_S = 10.0
# 轮内预算按工具分池：单工具的暴力试探不得饿死发现链（真机实测 probe_url 逐路径
# 猜接口烧光共享预算后，discover_login 被拒、页面分析整段跳过）。额度从宽——
# 只兜住失控循环，不卡正常调试（候选跨域验证、用户纠正后重试都有余量）
TOOL_BUDGETS: dict[str, int] = {
    "request": 25,  # 门控请求原语（v4：http_request 并入登录实测）：前端主包与分块
    # 抓取、登录实测、链式认证步全走 request——同一池防多入口绕限；从宽只兜
    # 逐路径扫描式空转
    "declare_token": 10,  # 事后声明式提取：不重发请求，试错只在路径拼写——从宽
    "discover_login": 5,  # 页面发现内含多条子请求，独立小池
    "search_content": 30,  # 分析主循环：真实会话中含噪检索词（post/user/token 命中
    # axios 库代码）与 js/css 双 hash 表分辨都要烧次数——额度从宽只兜空转
    "probe_protocol": 8,  # 裸探 + 带 configurable 重探 + modelId 试参（503 试错）+ 鉴权后
    # 重探——真机实测一轮正常调试即耗 4 次，用户纠正/换参后的重试都计于此
}


class SUTProbeToolServer(FetchMixin, DiscoveryMixin, ProtocolMixin, LoginMixin, ToolExporterMixin):
    """受控网络探测工具面：host 边界 + 注入防护 + 防锁 + 轮内预算。"""

    TOOL_SPECS: ClassVar[list[ToolSpec]] = [
        ToolSpec(
            name="request",
            description=(
                "门控请求原语（探测面的裸请求工具，抓取与接口调试同一出口）："
                'method/url/headers/body 自由构造（headers 用 "Key: Value"、多项以'
                " | 分隔），返回状态码 + 响应头 + 响应体。GET 即「抓取」：完整响应体"
                " 自动入缓存供 search_content 检索（返回含 cached_bytes 与"
                " search_hint）；非 GET 即接口调试——要看原始响应（405 的 Allow 头、"
                " 400/422 的业务错误消息、重定向 Location）用它。"
                " body/headers 支持 Jinja2 模板：凭证变量 {{ 字段 }} 由服务端从密钥区"
                " 注入（须带 ref，与包 credential_ref 同值；凭证值不经对话、返回中"
                " 不回显），带凭证请求首次外发前经用户授权一次；多步认证链用"
                " step=名字 声明本步响应，后续请求以 {{ stepN.路径 }} 引用其值"
                "（值全程服务端流动）。Authorization/Cookie 头禁传：已声明的会话凭证"
                " 自动挂载；新 host 首访会经用户确认；带凭证请求被 4xx/5xx 拒绝后"
                " 同组合不自动重发（防锁）。带凭证 2xx 响应在 declare_token 声明前"
                " 只回键路径结构不回原文（响应可能含会话凭证）"
            ),
            method="request",
        ),
        ToolSpec(
            name="discover_login",
            description=(
                "从页面登录地址发现登录 API（快速通道）：机械解析页面全部 form 与脚本清单"
                " → paths（自拟候选登录路径，| 分隔，≤10 条）定向检查 → OpenAPI 文档探测 →"
                " 兜底问答引导（不给凭证）；页面与同域脚本入缓存，未命中时用 search_content"
                " 深入分析前端包"
            ),
            method="discover_login",
        ),
        ToolSpec(
            name="search_content",
            description=(
                "在已抓取的页面/脚本内容中检索子串（大小写不敏感，非正则），返回带上下文"
                "的摘录（≤12 条）——前端包分析的主用工具。先 request(GET) 抓取目标再检索；"
                "一次没命中就换更短的词（业务词、请求构造痕迹、分包机制痕迹）"
            ),
            method="search_content",
        ),
        ToolSpec(
            name="probe_protocol",
            description=(
                "agent-protocol 符合性矩阵（与执行器契约同构）：POST /threads →"
                " commands（run.start 信封 + 会话路由头 + 已声明的会话凭证自动挂载）→"
                " state → stream 逐端点 ✅/❌（含写操作，收尾清理线程）。POST /threads"
                " 404 不影响判定——AG-UI 网关族由客户端生成线程 ID、首个 run.start"
                " 隐式建线程，协议判定以 send_command/run_wait 为准。"
                " configurable 传与 sut_config.configurable 同形的对象（如"
                ' {"modelId": "19"}）——网关要求业务参数时裸探会 400/422，带参重探'
                " 核心 ✅ 才算验证通过（执行器同款下发路径）；落盘前的最后一次协议"
                " 探测应携带最终参数"
            ),
            method="probe_protocol",
        ),
        ToolSpec(
            name="declare_token",
            description=(
                "声明会话凭证提取（登录实测成功后调用，事后声明不重发请求）："
                "token_path 用点分路径从该 ref 最近一次带凭证 2xx 响应的 JSON 中取值"
                "（数组用数字下标，如 data.0.token——以 request 返回的键路径结构树"
                " 为准）；token_source 三态：bearer（默认，Authorization: Bearer 自动"
                " 挂载）/ header:X（挂到自定义头 X）/ cookie:名字（会话 cookie——"
                " 响应 Set-Cookie 已按名提取，也可 token_path 从响应体取）。成功返回"
                " 可直接照抄的 sut_config_auth_snippet（原样写入包的 auth: 段，勿改写）；"
                " 路径提取失败会给出实际可用的键路径清单"
            ),
            method="declare_token",
        ),
        ToolSpec(
            name="ask_user",
            description=(
                "向用户提问，一次只问一个问题（多项信息拆成多次调用，问题不超 200 字）。"
                "kind 三态：text=开放答案（地址/描述，默认）；choice=明确候选，options 用 | 分隔"
                "（如 需要登录|免登录）；credential=凭证字段录入，必带 ref、field 与 desc——"
                "desc 用一句话说明该字段实际要输入什么（从你的分析结论得出），一次只录"
                "一个字段（输入直写密钥区不回流）。不要用 options 表达「请文本输入」之类的说明"
            ),
            method="ask_user",
        ),
    ]

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
        self._denied_hosts: set[str] = set()
        self.ask_fn = ask_fn
        self.credentials = credential_store
        self.log_path = log_path
        self._http_factory = http_client_factory
        # 预算/超时可注入（WorkbenchAgentConfig 探测档位默认，arch/15 §6.11.2）
        self.budgets = dict(budgets) if budgets is not None else dict(TOOL_BUDGETS)
        self.timeout_s = timeout_s
        self._turn_calls: dict[str, int] = {}
        # 抓取缓存（url → 完整内容）：前端包分析的存储侧，会话内跨轮有效
        # （预算按轮重置但分析状态不丢——新轮可直接检索续查）
        self._fetched: dict[str, str] = {}
        # 防锁：同 (ref, url, body) 凭证请求组合被认证层拒绝（4xx/5xx）即入锁——
        # 配置未变不重试；用户纠正字段/接口后模板变化视为新组合，允许再次实测；
        # 2xx 组合不入锁（declare_token 事后声明/修正提取不重发请求）
        self._login_tried: set[tuple[str, str, str]] = set()
        # 证据账本（落盘对账门禁的事实源，arch/15 §6.6 v3.6）：探测工具在验证
        # 成功时把事实**机械登记**于此（不经 LLM 转述），提交门禁用执行器同款
        # 解析逻辑与暂存 sut_configs 逐字段对账——验证结论到落盘配置的传递
        # 「原样即可、变形必被打回」
        self._verified_logins: dict[str, dict[str, str]] = {}  # ref(小写) → 实测事实
        self._verified_protocols: dict[str, dict[str, Any]] = {}  # host → 矩阵事实
        # 会话凭证服务端持有（v3.9，v4 扩展）：ref(小写) → {token, source}——
        # 已声明的凭证按 source 自动挂载（与执行器 mount_headers 三态同构，
        # cookie 型由共享 client 的 cookie jar 承载）；值不出现在任何工具返回里，
        # 不回流 LLM 上下文
        self._session_tokens: dict[str, dict[str, str]] = {}
        # 凭证外发授权账本（v4 D1）：(host, ref小写) 组合级——首次外发前经用户
        # 确认一次，同组合后续外发不再逐次打扰（每次外发仍留痕审计）
        self._credential_grants: set[tuple[str, str]] = set()
        # 最近一次带凭证请求的事实（ref → 原始模板/状态/响应/cookie 名值对）：
        # declare_token 事后声明式提取的唯一事实源（提取在此数据上进行，
        # 不重发请求）；值全部服务端保管
        self._last_credential_request: dict[str, dict[str, Any]] = {}
        # 链式认证步骤（v4）：步骤名 → 该步响应 JSON——后续 request 的模板变量
        # {{ stepN.路径 }} 引用其值（值服务端流动，不经对话）
        self._step_responses: dict[str, Any] = {}
        # 会话级共享 AsyncClient（与执行器 channels/base.py 同构：连接池 +
        # cookie jar——cookie 型凭证与会话粘性靠它），会话结束 aclose()
        self._shared_client: Any = None

    # ── 会话挂点与共享设施（mixin 协作契约的实现侧） ───────────────

    def new_turn(self) -> None:
        """每轮 REPL 开始时由 WorkbenchAgent 调用：重置各工具轮内预算。

        抓取缓存**跨轮保留**（会话内有效，容量有界）——预算报错指引「用户回复
        任意消息开启新一轮后继续验证」，若连缓存一起清空，新轮先要把前端主包
        重抓重搜才能回到原地，放大的预算也会先耗在重复劳动上。
        """
        self._turn_calls.clear()

    def _log(self, tool: str, **payload: Any) -> None:
        if self.log_path is None:
            return
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        entry = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "tool": tool, **payload}
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")

    # ── 证据账本（门禁对账的事实源：登记/查询收口在此，mixin 经助手写入） ──

    def _record_login(self, fact: dict[str, str]) -> None:
        """登录实测成功 → 登记账本（同 ref 取最新一次成功）。"""
        self._verified_logins[fact["ref"].lower()] = fact
        self._log("login_verified", ref=fact["ref"], url=fact["url"])

    def _record_protocol(self, host: str, flavor: str, steps: dict[str, bool]) -> None:
        """协议矩阵实测 → 协议账本（含失败矩阵——「探测过但未支持」也是事实）。"""
        self._verified_protocols[host.lower()] = {"flavor": flavor, "steps": steps}
        self._log("protocol_probed", host=host, flavor=flavor, steps=steps)

    def verified_login(self, ref: str) -> dict[str, str] | None:
        """查登录实测事实（落盘对账门禁用）。"""
        return self._verified_logins.get(ref.lower())

    def verified_protocol(self, host: str) -> dict[str, Any] | None:
        """查协议矩阵事实（落盘对账门禁用）。"""
        return self._verified_protocols.get(host.lower())

    @property
    def login_hosts(self) -> set[str]:
        """本会话登录实测成功过的接口域（小写）——协议探测的候选证据源。"""
        hosts: set[str] = set()
        for fact in self._verified_logins.values():
            if host := _host_of(fact.get("url", "")):
                hosts.add(host.lower())
        return hosts

    def _store_token(self, ref: str, token: str, source: str = "bearer") -> None:
        """声明提取的会话凭证服务端持有（仅内部使用，不进任何返回值）。"""
        self._session_tokens[ref.lower()] = {"token": token, "source": source}

    @property
    def auth_headers(self) -> dict[str, str]:
        """已声明会话凭证的自动挂载头（与执行器 mount_headers 三态同构，无则空）。

        bearer → Authorization: Bearer；header:X → 自定义头；cookie → 空字典
        （cookie 由共享 client 的 cookie jar 承载，declare_token 落 jar）。
        """
        if not self._session_tokens:
            return {}
        entry = list(self._session_tokens.values())[-1]
        source = entry.get("source", "bearer")
        if source == "cookie":
            return {}
        if source.startswith("header:"):
            return {source[len("header:") :]: entry["token"]}
        return {"Authorization": f"Bearer {entry['token']}"}

    def _budget(self, tool: str) -> dict[str, str] | None:
        limit = self.budgets.get(tool)
        if limit is None:
            return None
        self._turn_calls[tool] = self._turn_calls.get(tool, 0) + 1
        if self._turn_calls[tool] > limit:
            self._log(tool, event="budget_exceeded")
            # 达上限 ≠ 收尾信号：指引继续验证而非把未验证猜测写进配置
            return {
                "error": (
                    f"本轮 {tool} 调用已达上限（{limit}）。请把已有证据如实呈现给用户并询问"
                    f"下一步——可请用户回复任意消息开启新一轮（探测预算按轮重置）后继续验证；"
                    f"未经验证的接口/字段不得当作结论写入 sut_configs"
                )
            }
        return None

    def _host_gate(self, url: str) -> str | None:
        host = _host_of(url)
        if not host:
            return f"无法解析 host: {url}"
        host = host.lower()
        if host in self._denied_hosts:
            return f"该 host 此前已被用户拒绝，勿再试探: {host}——请与用户确认正确的地址"
        if host not in self.allowed_hosts:
            return (
                f"host {host} 未获用户授权（红线：仅可访问用户提供或确认过的 host）。"
                f"请先 ask_user 征得用户对该 host 的确认后再试"
            )
        return None

    async def _ensure_host(self, url: str) -> str | None:
        """host 边界：未授权 host 经 ask_user 征得用户同意后放行（红线 2）。"""
        err = self._host_gate(url)
        if err is None:
            return None
        host = _host_of(url)
        if host.lower() in self._denied_hosts:
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
            self._log("host_authorized", host=host)
            return None
        self._denied_hosts.add(host.lower())
        self._log("host_denied", host=host)
        return f"用户拒绝访问 {host}，不得探测该 host；请与用户确认正确的地址"

    async def _client(self) -> Any:
        """会话级共享 AsyncClient（懒建）：连接池复用 + cookie jar 跨请求保持。

        与执行器通道同构（channels/base.py）：登录态 cookie、会话粘性都靠共享
        client 的 jar——v3.x 每请求新建 client 丢 cookie 的宽度裂缝在此消灭。
        会话结束经 aclose() 释放。
        """
        if self._shared_client is None:
            if self._http_factory is not None:
                self._shared_client = self._http_factory()
            else:
                import httpx

                self._shared_client = httpx.AsyncClient(
                    timeout=self.timeout_s, follow_redirects=False
                )
        return self._shared_client

    def _borrow_client(self) -> Any:
        """``async with`` 形态借用共享 client（退出时不关闭——归会话统一释放）。

        供多请求长块（协议矩阵/页面发现）沿用原 ``async with client_cm`` 缩进，
        语义从「with 即关闭」变为「with 即借用」。
        """
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def _cm() -> Any:
            yield await self._client()

        return _cm()

    async def aclose(self) -> None:
        """释放共享 client（会话结束/Agent 关停时调用；幂等）。"""
        if self._shared_client is not None:
            try:
                await self._shared_client.aclose()
            except Exception:  # noqa: BLE001 — 释放失败不阻断收尾
                pass
            self._shared_client = None
