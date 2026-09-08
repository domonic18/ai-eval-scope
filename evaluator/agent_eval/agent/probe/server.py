"""SUTProbeToolServer — SUT 接入调试受控网络工具面的组装壳（组合模式薄委托面）。

与文件沙盒（workbench_tools，无网络不变式）并列的独立 server：创建场景包时由
Agent 主动探测被测系统（地址可达性 / agent-protocol 符合性 / 登录 API 发现与
实测），**验证过的结论才经 staging 门禁写进 sut_configs/**。真实实现按域拆分：
ProbeContext（context.py，共享状态与红线设施）+ 每域一个工具类——本壳只做装配
与委托，外部 API（tests / workbench_agent）依赖的名字全部保留；
「一域一 server」形态不变，拆的是实现不是边界。

ask_user 桥接 CLI 交互原语（文本/单选/凭证隐藏输入直写 secrets，值不回流 LLM
上下文）；非交互（``--yes`` CI）形态 ask_fn 为空 → 返回「需交互」错误。
工具异常以 ``{"error": ...}`` 返回交 Agent 自修复（tool_guard 精神）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar

from agent_eval.agent.probe.ask_user import AskUserTool
from agent_eval.agent.probe.context import ProbeContext
from agent_eval.agent.probe.discovery import DiscoveryTool
from agent_eval.agent.probe.protocol import ProtocolTool
from agent_eval.agent.probe.request import RequestTool
from agent_eval.agent.probe.search import _DEFAULT_CONTEXT, SearchTool
from agent_eval.agent.probe.specs import PROBE_TIMEOUT_S, PROBE_TOOL_SPECS
from agent_eval.agent.probe.tokens import TokenTool
from agent_eval.agent.tools import ToolExporterMixin, ToolSpec


class SUTProbeToolServer(ToolExporterMixin):
    """受控网络探测工具面：host 边界 + 注入防护 + 防锁 + 轮内预算。"""

    TOOL_SPECS: ClassVar[list[ToolSpec]] = PROBE_TOOL_SPECS

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
        self._ctx = ProbeContext(
            allowed_hosts=allowed_hosts,
            ask_fn=ask_fn,
            credential_store=credential_store,
            log_path=log_path,
            http_client_factory=http_client_factory,
            budgets=budgets,
            timeout_s=timeout_s,
        )
        self._request = RequestTool(self._ctx)
        self._search = SearchTool(self._ctx)
        self._discovery = DiscoveryTool(self._ctx)
        self._protocol = ProtocolTool(self._ctx)
        self._tokens = TokenTool(self._ctx)
        self._ask = AskUserTool(self._ctx)

    # ── 工具委托（签名逐字复制：StructuredTool 据此推导参数 Schema） ──

    async def request(
        self,
        method: str,
        url: str,
        headers: str = "",
        body: str = "",
        ref: str = "",
        step: str = "",
    ) -> dict[str, Any]:
        """门控请求原语——抓取与接口调试（含登录实测）同一出口。"""
        return await self._request.request(
            method, url, headers=headers, body=body, ref=ref, step=step
        )

    async def discover_login(self, page_url: str, paths: str = "") -> dict[str, Any]:
        """登录 API 快速通道：机械解析 + 定向探测，语义判断全部交 Agent。"""
        return await self._discovery.discover_login(page_url, paths=paths)

    async def search_content(self, pattern: str, context: int = _DEFAULT_CONTEXT) -> dict[str, Any]:
        """在已抓取内容中检索子串，返回带上下文的摘录。"""
        return await self._search.search_content(pattern, context=context)

    async def probe_protocol(
        self, base_url: str, flavor: str = "commands", configurable: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """agent-protocol 符合性矩阵（含写操作，收尾清理）。"""
        return await self._protocol.probe_protocol(
            base_url, flavor=flavor, configurable=configurable
        )

    async def declare_token(
        self,
        ref: str,
        token_path: str = "",
        token_source: str = "Bearer",
        expires_in_path: str = "",
    ) -> dict[str, Any]:
        """事后声明式会话凭证提取：在该 ref 最近一次带凭证 2xx 响应上提取。"""
        return await self._tokens.declare_token(
            ref,
            token_path=token_path,
            token_source=token_source,
            expires_in_path=expires_in_path,
        )

    async def ask_user(
        self,
        question: str,
        options: str = "",
        kind: str = "text",
        ref: str = "",
        field: str = "",
        desc: str = "",
    ) -> dict[str, Any]:
        """向用户提问（文本/单选/凭证三态）；凭证录入直写密钥区不回流。"""
        return await self._ask.ask_user(
            question, options=options, kind=kind, ref=ref, field=field, desc=desc
        )

    # ── 设施委托 ─────────────────────────────────────────────────

    def new_turn(self) -> None:
        """每轮 REPL 开始时由 WorkbenchAgent 调用：重置各工具轮内预算。"""
        self._ctx.new_turn()

    async def aclose(self) -> None:
        """释放共享 client（会话结束/Agent 关停时调用；幂等）。"""
        await self._ctx.aclose()

    def verified_login(self, ref: str) -> dict[str, str] | None:
        """查登录实测事实（落盘对账门禁用）。"""
        return self._ctx.verified_login(ref)

    def verified_protocol(self, host: str) -> dict[str, Any] | None:
        """查协议矩阵事实（落盘对账门禁用）。"""
        return self._ctx.verified_protocol(host)

    # ── 兼容别名（测试/门禁专用，勿在新代码使用） ────────────────

    def _record_login(self, fact: dict[str, str]) -> None:
        self._ctx.record_login(fact)

    def _record_protocol(self, host: str, flavor: str, steps: dict[str, bool]) -> None:
        self._ctx.record_protocol(host, flavor, steps)

    def _store_token(self, ref: str, token: str, source: str = "bearer") -> None:
        self._ctx.store_token(ref, token, source)

    def _cache_content(self, url: str, content: str) -> None:
        self._ctx.cache_content(url, content)

    def _borrow_client(self) -> Any:
        return self._ctx.borrow_client()

    # ── 状态透传（返回本体：测试/门禁的原地修改语义不变） ─────────

    @property
    def allowed_hosts(self) -> set[str]:
        return self._ctx.allowed_hosts

    @property
    def credentials(self) -> Any:
        """凭证库（历史公开名；ProbeContext 侧与构造参数同名 credential_store）。"""
        return self._ctx.credential_store

    @property
    def budgets(self) -> dict[str, int]:
        return self._ctx.budgets

    @property
    def timeout_s(self) -> float:
        return self._ctx.timeout_s

    @property
    def auth_headers(self) -> dict[str, str]:
        return self._ctx.auth_headers

    @property
    def login_hosts(self) -> set[str]:
        return self._ctx.login_hosts

    @property
    def protocol_hosts(self) -> set[str]:
        return self._ctx.protocol_hosts

    @property
    def _turn_calls(self) -> dict[str, int]:
        return self._ctx.turn_calls

    @property
    def log_path(self) -> Path | None:
        return self._ctx.log_path

    @log_path.setter
    def log_path(self, value: Path | None) -> None:
        self._ctx.log_path = value

    @property
    def ask_fn(self) -> Any:
        return self._ctx.ask_fn

    @ask_fn.setter
    def ask_fn(self, value: Any) -> None:
        self._ctx.ask_fn = value
