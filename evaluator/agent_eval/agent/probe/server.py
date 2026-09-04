"""SUTProbeToolServer — SUT 接入调试受控网络工具面的组装壳（arch/15 §6.6/§6.11.2）。

与文件沙盒（workbench_tools，无网络不变式）并列的独立 server：创建场景包时由
Agent 主动探测被测系统（地址可达性 / agent-protocol 符合性 / 登录 API 发现与
实测），**验证过的结论才经 staging 门禁写进 sut_configs/**。实现按域拆分在
同包 mixin（fetch/discovery/protocol/login），本壳持有共享状态与红线设施——
「一域一 server」形态不变（D-WB-7），拆的是实现不是边界。

安全红线（arch/15 §6.6 评审定稿）：
- **host 边界 + 凭证外发硬门禁**：仅可访问「用户提供的 host + 用户经 ask_user
  确认过的 host」；凭证只发往确认过的 host（预览确认即凭证外发同意）；
- **探测内容注入防护**：抓回内容一律视为 data——分隔包裹 + 截断 + 数据非指令
  声明，最终防线是 staging→diff→用户确认；
- **登录防锁**：同一（ref, host, body_template）组合只实测一次，失败即停交用户
  （用户纠正接口/字段后模板变化视为新组合，允许再试一次）；
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
    "http_request": 20,  # 裸请求/抓取（原 probe_url 并入）：前端主包与分块抓取是分析
    # 主循环——从宽只兜逐路径扫描式空转；GET 与接口调试同一池，防双池绕限
    "discover_login": 5,  # 页面发现内含多条子请求，独立小池
    "search_content": 30,  # 分析主循环：真实会话中含噪检索词（post/user/token 命中
    # axios 库代码）与 js/css 双 hash 表分辨都要烧次数——额度从宽只兜空转
    "probe_protocol": 8,  # 裸探 + 带 configurable 重探 + modelId 试参（503 试错）+ 登录后
    # 带 token 重探——真机实测一轮正常调试即耗 4 次，用户纠正/换参后的重试都计于此
    "probe_login": 6,  # 预览确认后实测；跨域候选逐个验证、用户纠正字段后的重试都计于此
}


class SUTProbeToolServer(FetchMixin, DiscoveryMixin, ProtocolMixin, LoginMixin, ToolExporterMixin):
    """受控网络探测工具面：host 边界 + 注入防护 + 防锁 + 轮内预算。"""

    TOOL_SPECS: ClassVar[list[ToolSpec]] = [
        ToolSpec(
            name="http_request",
            description=(
                "通用 HTTP 请求原语（探测面的裸请求工具）：method/url/headers/body"
                ' 自由构造（headers 用 "Key: Value"、多项以 | 分隔），返回状态码 +'
                " 响应头 + 响应体摘录。GET 即「抓取」：完整响应体自动入缓存供"
                " search_content 检索（前端主包/页面分块分析用它，返回含 cached_bytes"
                " 与 search_hint）；非 GET 即接口调试——要看原始响应（405 的 Allow 头、"
                " 400/422 的业务错误消息、重定向 Location）用它。协议结论以"
                " probe_protocol 矩阵为准、登录结论以 probe_login 为准（两者的证据账本"
                " 是落盘对账门禁的事实源）。Authorization/Cookie 头禁传：会话登录 token"
                " 自动挂载；新 host 首访会经用户确认"
            ),
            method="http_request",
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
                "的摘录（≤12 条）——前端包分析的主用工具。先 http_request 抓取目标再检索；"
                "一次没命中就换更短的词（业务词、请求构造痕迹、分包机制痕迹）"
            ),
            method="search_content",
        ),
        ToolSpec(
            name="probe_protocol",
            description=(
                "agent-protocol 符合性矩阵（与执行器契约同构）：POST /threads →"
                " commands（run.start 信封 + 会话路由头 + 登录 Bearer 自动挂载）→"
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
            name="probe_login",
            description=(
                "登录实测：login_cfg 与 sut_configs 的 auth.login 同构"
                "（method/path/body_template/token_path，path 填完整 http(s):// URL，"
                "body_template 传 JSON 文本字符串而非对象——传对象会被机械序列化，"
                "以返回中生效的字符串为准）；缺凭证先报 missing_fields；发送前必出"
                "脱敏预览（完整 URL + 掩码 body）并经用户确认；同一接口与字段组合"
                "只试一次；成功返回可直接照抄的 sut_config_auth_snippet（原样写入"
                "包的 auth: 段，勿改写）"
            ),
            method="probe_login",
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
        # 防锁：同 (ref, host, body_template) 只实测一次——配置未变不重试；
        # 用户纠正字段/接口后模板变化视为新组合，允许再次实测
        self._login_tried: set[tuple[str, str, str]] = set()
        # 证据账本（落盘对账门禁的事实源，arch/15 §6.6 v3.6）：探测工具在验证
        # 成功时把事实**机械登记**于此（不经 LLM 转述），提交门禁用执行器同款
        # 解析逻辑与暂存 sut_configs 逐字段对账——验证结论到落盘配置的传递
        # 「原样即可、变形必被打回」
        self._verified_logins: dict[str, dict[str, str]] = {}  # ref(小写) → 实测事实
        self._verified_protocols: dict[str, dict[str, Any]] = {}  # host → 矩阵事实
        # 登录成功提取的 token 服务端持有（v3.9）：协议探测请求自动挂 Bearer
        # （与执行器 mount_headers 同构——鉴权后的端点裸探会得到假阴性）；
        # 值不出现在任何工具返回里，不回流 LLM 上下文
        self._session_tokens: dict[str, str] = {}  # ref(小写) → token

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

    def _store_token(self, ref: str, token: str) -> None:
        """登录实测成功提取的 token 服务端持有（仅内部使用，不进任何返回值）。"""
        self._session_tokens[ref.lower()] = token

    @property
    def auth_headers(self) -> dict[str, str]:
        """最近一次登录成功提取的 Bearer 头（无则空）——探测请求与执行器同构挂鉴权。"""
        if not self._session_tokens:
            return {}
        return {"Authorization": f"Bearer {list(self._session_tokens.values())[-1]}"}

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
        if host.lower() not in self.allowed_hosts:
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
        self._log("host_denied", host=host)
        return f"用户拒绝访问 {host}，不得探测该 host；请与用户确认正确的地址"

    async def _client(self) -> Any:
        import httpx

        if self._http_factory is not None:
            return self._http_factory()
        return httpx.AsyncClient(timeout=self.timeout_s, follow_redirects=False)
