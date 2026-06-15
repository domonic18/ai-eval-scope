"""EvaluationAgent — Agent 自适应评估（可选评估模式）。

读取 Markdown 评测计划，自主完成评估任务。
Sprint 8+ 实现，当前为骨架文件。
"""

from __future__ import annotations

from typing import Any


class EvaluationAgent:
    """EvaluationAgent — Agent 自适应评估。

    通过 EvalToolServer（MCP Tools）调用评估器，
    根据 Markdown 评测计划自适应执行评估流程。

    注意：本类将在后续迭代中完整实现。当前仅提供接口骨架。
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}

    async def evaluate(
        self,
        package_path: str,
        rule_set_path: str,
        eval_plan_path: str | None = None,
    ) -> dict[str, Any]:
        """执行自适应评估。

        Args:
            package_path: ExecutionPackage 目录路径。
            rule_set_path: 规则集文件路径。
            eval_plan_path: Markdown 评测计划路径（可选）。

        Returns:
            评估结果字典。

        Raises:
            NotImplementedError: 当前迭代尚未实现。
        """
        raise NotImplementedError("EvaluationAgent.evaluate() 将在后续迭代中实现。")
