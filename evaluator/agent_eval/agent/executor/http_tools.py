"""GenericHttp 语义工具面（generic_http 通道，arch/03 §4.2）。

sut_request 单语义工具：请求模板渲染与响应提取都在通道内完成——执行
Agent 只给 input 与 metadata，不手搓请求（与 AgentProtocolToolServer 的
agent_run 同一套约定；last_run 契约同构，ExecutionAgent 物化 answer.md
无需感知通道差异）。
"""

from __future__ import annotations

from typing import Any

from agent_eval.agent.core.tools import ToolExporterMixin, ToolSpec
from agent_eval.agent.executor.protocol_tools import bounded_result, tool_guard
from agent_eval.execution.channels.generic_http import GenericHttpChannel

TOOL_SPECS: list[ToolSpec] = [
    ToolSpec(
        name="sut_request",
        description=(
            "向被测系统发送一次请求（请求模板与响应提取按被测系统配置预置），"
            "返回终态与回答文本（text）"
        ),
        method="sut_request",
    ),
]


class GenericHttpToolServer(ToolExporterMixin):
    """generic_http 语义工具注册表，绑定一个 GenericHttpChannel。"""

    TOOL_SPECS = TOOL_SPECS

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

    def _record_last_run(self, result: dict[str, Any]) -> None:
        """记录最近一次请求的状态与回答文本（与 AgentProtocolToolServer 同契约）。"""
        output = result.get("output") or {}
        self.last_run = {
            "status": result.get("status"),
            "run_id": (result.get("run") or {}).get("run_id"),
            "text": result.get("text") or output.get("text") or "",
        }

    @tool_guard
    async def sut_request(
        self,
        input: dict[str, Any] | str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """向被测系统发送一次请求：input 进入预置请求模板，返回归一化结果。"""
        result = await self.channel.run(
            input, metadata={**self.default_metadata, **(metadata or {})}
        )
        self._record_last_run(result)
        return bounded_result(result)


__all__ = ["GenericHttpToolServer"]
