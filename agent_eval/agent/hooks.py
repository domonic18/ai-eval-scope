"""Agent Hooks — Agent 运行时的监控/预算/安全钩子。

提供 PreToolUse、PostToolUse 等生命周期钩子，
用于预算控制、日志记录、安全校验等。
Sprint 8 实现，当前为骨架文件。
"""

from __future__ import annotations

from typing import Any


class BudgetController:
    """预算控制器，监控 Agent 执行成本。

    基于 token 用量估算成本，支持 max_budget_usd 硬性限制。

    注意：本类将在 Sprint 8 中完整实现。当前仅提供接口骨架。
    """

    def __init__(self, max_budget_usd: float, warn_threshold: float = 0.8) -> None:
        self.max_budget_usd = max_budget_usd
        self.warn_threshold = warn_threshold
        self.spent_usd: float = 0.0

    def check(self) -> str:
        """检查当前预算状态。

        Returns:
            "ok" | "warning" | "exceeded"
        """
        if self.spent_usd >= self.max_budget_usd:
            return "exceeded"
        if self.spent_usd >= self.max_budget_usd * self.warn_threshold:
            return "warning"
        return "ok"


class SessionLogger:
    """Agent 执行会话的结构化日志记录器。

    确保所有 Agent 行为都输出为机器可解析的 JSON Lines。

    注意：本类将在 Sprint 8 中完整实现。当前仅提供接口骨架。
    """

    def __init__(self, run_id: str, task_id: str, log_dir: Any = None) -> None:
        self.run_id = run_id
        self.task_id = task_id
