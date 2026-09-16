"""GenericHttp 语义工具面（generic_http 通道，arch/03 §4.2）。

sut_request 单语义工具：请求模板渲染与响应提取都在通道内完成——执行
Agent 只给 input 与 metadata，不手搓请求（与 AgentProtocolToolServer 的
agent_run 同一套约定；last_run 契约同构，ExecutionAgent 物化 answer.md
无需感知通道差异）。
"""

from __future__ import annotations

import time
from typing import Any

from agent_eval.agent.core.tools import ToolExporterMixin, ToolSpec
from agent_eval.agent.executor.ledger import ResourceLedger, uninjected_ledger_refusal
from agent_eval.agent.executor.protocol_tools import bounded_result, tool_guard
from agent_eval.execution.channels.generic_http import GenericHttpChannel

TOOL_SPECS: list[ToolSpec] = [
    ToolSpec(
        name="sut_request",
        description=(
            "向被测系统发送一次请求（请求模板与响应提取按被测系统配置预置），"
            "返回终态与回答文本（text）。多轮会话自动续接（配置了 once 步时"
            "历史会话跨调用复用）；仅当明确要开启全新会话时才传 new_session=true"
        ),
        method="sut_request",
    ),
]


class GenericHttpToolServer(ToolExporterMixin):
    """generic_http 语义工具注册表，绑定一个 GenericHttpChannel。"""

    TOOL_SPECS = TOOL_SPECS
    discipline_key = "generic_http"  # 通道专属纪律段（execution_agent_prompts.yaml）

    def __init__(
        self,
        channel: GenericHttpChannel,
        *,
        default_metadata: dict[str, Any] | None = None,
    ) -> None:
        """初始化工具注册表。

        Args:
            channel: generic_http 通道实例。
            default_metadata: 附加到每次请求模板变量的元数据（如
                eval_run_id/task_id/sut_name，可被 request_template 引用）。
        """
        self.channel = channel
        self.default_metadata = default_metadata or {}
        # 最近一次 SUT 请求摘要（ExecutionPackage trace 回填 SUT 回答文本用）
        self.last_run: dict[str, Any] | None = None
        # 交互预算账本（arch/16 §4.3）——缺省 None=fail-closed（未注入即拒绝，
        # 见 sut_request）；由 ExecutionAgent 逐任务注入新实例
        self.ledger: ResourceLedger | None = None
        # once 步会话键（plan/06 M1）——ExecutionAgent.run_task 逐任务注入
        # task.id，多任务隔离由键空间机械保证（不依赖 Agent 在 metadata 自觉传）
        self.current_session_key: str | None = None

    def _record_last_run(self, result: dict[str, Any], input: Any = None) -> None:
        """记录最近一次请求的状态、输入与回答文本（与 AgentProtocolToolServer 同契约）。

        input 一并记录：ExecutionAgent 的机械回显守卫据此判定「SUT 返回=请求原文」。
        """
        output = result.get("output") or {}
        self.last_run = {
            "status": result.get("status"),
            "run_id": (result.get("run") or {}).get("run_id"),
            "text": result.get("text") or output.get("text") or "",
            "input": input,
        }

    @tool_guard
    async def sut_request(
        self,
        input: dict[str, Any] | str,
        metadata: dict[str, Any] | None = None,
        new_session: bool = False,
    ) -> dict[str, Any]:
        """向被测系统发送一次请求：input 进入预置请求模板，返回归一化结果。

        多轮会话自动续接（plan/06 M1）：配置了 once 步时该请求与此前调用共享
        同一会话（键由执行框架按任务注入）；``new_session=True`` 丢弃当前会话
        整链重建——仅明确要换会话时使用，勿自作主张。

        闸门走 sut_call 动作（额度=sut_calls_total）：一次任务常需多请求
        （登录/提交/取件），不受 dispatch 单发限制；once 步次轮命中缓存跳过
        请求但仍计一次（授权=尝试语义）。
        """
        if self.ledger is None:
            # fail-closed：账本未注入（装配遗漏）时拒绝而非放行——无账本不能
            # 等于无额度，否则该工具即成对被测系统的无限额调用口
            return uninjected_ledger_refusal("sut_call")
        refused = self.ledger.authorize("sut_call")
        if refused is not None:
            return refused
        started = time.monotonic()
        result = await self.channel.run(
            input,
            metadata={**self.default_metadata, **(metadata or {})},
            session_key=self.current_session_key or "default",
            new_session=new_session,
        )
        if self.ledger is not None:
            self.ledger.record("sut_call", "ok", duration_s=time.monotonic() - started)
        self._record_last_run(result, input)
        return bounded_result(result)


__all__ = ["GenericHttpToolServer"]
