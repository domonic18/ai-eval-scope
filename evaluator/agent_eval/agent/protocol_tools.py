"""Agent Protocol 语义工具面（arch/03 §4.0.6-b）。

取代手搓 HTTP 请求：agent_run / agent_run_stream / create_thread /
run_on_thread / cancel_run / get_agent_info 六个语义工具，封装
AgentProtocolChannel 暴露给 DeepAgents 显式绑定（ToolExporterMixin）。
"""

from __future__ import annotations

import functools
import json
from collections.abc import Awaitable, Callable
from typing import Any

from agent_eval.agent.tools import ToolExporterMixin, ToolSpec, truncate
from agent_eval.core.exceptions import AgentEvalError
from agent_eval.execution.channels.agent_protocol import AgentProtocolChannel

# 工具结果中大体量字段的截断上限（上下文经济性，非业务阈值）
VALUES_MAX_CHARS = 4000
EVENT_DATA_MAX_CHARS = 500
MAX_STREAM_EVENTS = 100


def tool_guard(
    fn: Callable[..., Awaitable[dict[str, Any]]],
) -> Callable[..., Awaitable[dict[str, Any]]]:
    """通道异常 → failed 结果（执行 Agent 可据以重试/降级/写错误包，而非中断图）。"""

    @functools.wraps(fn)
    async def wrapper(*args: Any, **kwargs: Any) -> dict[str, Any]:
        try:
            return await fn(*args, **kwargs)
        except AgentEvalError as e:
            return {
                "status": "failed",
                "error": {
                    "type": type(e).__name__,
                    "message": truncate(str(e), VALUES_MAX_CHARS),
                },
            }

    return wrapper


TOOL_SPECS: list[ToolSpec] = [
    ToolSpec(
        name="agent_run",
        description="执行被测 Agent（Agent Protocol）：wait 阻塞 / background 后台 / stream 流式，返回终态与产出物",
        method="agent_run",
    ),
    ToolSpec(
        name="agent_run_stream",
        description="流式执行被测 Agent 并聚合为完整输出 + 过程事件列表（需过程数据时使用）",
        method="agent_run_stream",
    ),
    ToolSpec(
        name="create_thread",
        description="创建多轮会话线程（对话式任务用；每 thread 同时仅一个活跃 run）",
        method="create_thread",
    ),
    ToolSpec(
        name="run_on_thread",
        description="在既有线程上执行一轮（多轮对话任务的后续轮次）",
        method="run_on_thread",
    ),
    ToolSpec(
        name="cancel_run",
        description="主动取消 run（interrupt 打断 / rollback 回滚，rollback 仅系统声明支持时用）",
        method="cancel_run",
    ),
    ToolSpec(
        name="get_agent_info",
        description="能力与 schema 发现（agents/search + schemas，接入自检用）",
        method="get_agent_info",
    ),
]


class AgentProtocolToolServer(ToolExporterMixin):
    """Agent Protocol 语义工具注册表，绑定一个 AgentProtocolChannel。"""

    TOOL_SPECS = TOOL_SPECS

    def __init__(
        self,
        channel: AgentProtocolChannel,
        *,
        default_metadata: dict[str, Any] | None = None,
    ) -> None:
        """初始化工具注册表。

        Args:
            channel: Agent Protocol 通道实例。
            default_metadata: 附加到每次 run 的元数据（如 eval_run_id/sut_name，
                §4.0.6-e：便于被测系统侧审计与限流豁免协商）。
        """
        self.channel = channel
        self.default_metadata = default_metadata or {}

    @tool_guard
    async def agent_run(
        self,
        input: dict[str, Any] | str,
        exec_mode: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """执行被测 Agent：按 exec_mode 走 wait/background/stream。"""
        result = await self.channel.run(
            input, exec_mode=exec_mode, metadata=self._merge_metadata(metadata)
        )
        return _bounded_result(result)

    @tool_guard
    async def agent_run_stream(
        self,
        input: dict[str, Any] | str,
        stream_mode: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """流式执行并聚合（未知事件保留在 events，完整原文可写入 trace）。"""
        result = await self.channel.run_stream(
            input, stream_mode=stream_mode, metadata=self._merge_metadata(metadata)
        )
        result["events"] = [
            {
                "event": e.get("event"),
                "data": truncate(
                    json.dumps(e.get("data"), ensure_ascii=False, default=str), EVENT_DATA_MAX_CHARS
                ),
            }
            for e in result.get("events", [])[:MAX_STREAM_EVENTS]
        ]
        return _bounded_result(result)

    @tool_guard
    async def create_thread(self, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        """创建多轮会话线程。"""
        return await self.channel.create_thread(self._merge_metadata(metadata))

    @tool_guard
    async def run_on_thread(
        self,
        thread_id: str,
        input: dict[str, Any] | str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """在既有线程上执行一轮。"""
        result = await self.channel.run_on_thread(
            thread_id, input, metadata=self._merge_metadata(metadata)
        )
        return _bounded_result(result)

    @tool_guard
    async def cancel_run(self, run_id: str, action: str = "interrupt") -> dict[str, Any]:
        """主动取消 run。"""
        return await self.channel.cancel_run(run_id, action)

    @tool_guard
    async def get_agent_info(self, agent_id: str | None = None) -> dict[str, Any]:
        """能力与 schema 发现。"""
        return await self.channel.get_agent_info(agent_id)

    def _merge_metadata(self, metadata: dict[str, Any] | None) -> dict[str, Any]:
        return {**self.default_metadata, **(metadata or {})}


def _bounded_result(result: dict[str, Any]) -> dict[str, Any]:
    """截断大体量字段（values/messages/events 文本化），保留状态与产出物结构。"""
    bounded = dict(result)
    for field in ("values", "messages", "text"):
        if field in bounded and bounded[field] is not None:
            if isinstance(bounded[field], str):
                bounded[field] = truncate(bounded[field], VALUES_MAX_CHARS)
            else:
                bounded[field] = truncate(
                    json.dumps(bounded[field], ensure_ascii=False, default=str),
                    VALUES_MAX_CHARS,
                )
    if "error" in bounded and isinstance(bounded["error"], dict):
        message = bounded["error"].get("message")
        if isinstance(message, str):
            bounded["error"]["message"] = truncate(message, VALUES_MAX_CHARS)
    return bounded


__all__ = ["AgentProtocolToolServer"]
