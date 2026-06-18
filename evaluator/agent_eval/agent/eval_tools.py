"""EvalToolServer — 评估器工具（MCP）。

为 EvaluationAgent 提供评估器调用能力的 MCP Tools。
后续迭代实现，当前为骨架文件。
"""

from __future__ import annotations

from typing import Any


class EvalToolServer:
    """评估器工具服务器，为 EvaluationAgent 提供评估器调用能力。

    注意：本类将在后续迭代中完整实现。当前仅提供接口骨架。
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}

    def get_tool_names(self) -> list[str]:
        """返回所有注册的评估工具名称。"""
        return [
            "evaluate_constraint",
            "get_evaluator_info",
            "list_evaluators",
        ]
