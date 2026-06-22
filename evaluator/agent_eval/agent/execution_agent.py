"""ExecutionAgent — 基于 Claude Agent SDK 的执行 Agent。

端到端驱动评测执行流程：理解任务、调用 SUT Tools、处理错误、收集结果、生成 ExecutionPackage。
Sprint 8 实现，当前为骨架文件。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent_eval.execution.models import AgentConfig, Task, TaskSet
    from agent_eval.storage.package import ExecutionPackage


class ExecutionAgent:
    """基于 Claude Agent SDK 的执行 Agent，端到端驱动评测执行流程。

    ExecutionAgent 接收 Task，通过调用 SUT Tools（MCP）与被测系统交互，
    自主完成请求构造、错误处理、结果收集，最终生成 ExecutionPackage。

    注意：本类将在 Sprint 8 中完整实现。当前仅提供接口骨架。
    """

    def __init__(self, config: AgentConfig) -> None:
        self.config = config

    async def run_task(self, task: Task) -> ExecutionPackage:
        """执行单个任务，返回 ExecutionPackage。

        Args:
            task: 待执行的评测任务。

        Returns:
            包含执行结果的 ExecutionPackage。

        Raises:
            NotImplementedError: 当前迭代尚未实现。
        """
        raise NotImplementedError("ExecutionAgent.run_task() 将在 Sprint 8 中实现。")

    async def run_task_set(self, task_set: TaskSet) -> list[ExecutionPackage]:
        """批量执行任务集，返回执行包列表。

        Args:
            task_set: 待执行的任务集。

        Returns:
            执行包列表。

        Raises:
            NotImplementedError: 当前迭代尚未实现。
        """
        raise NotImplementedError("ExecutionAgent.run_task_set() 将在 Sprint 8 中实现。")
