"""BudgetController — Agent 执行成本计量与硬性预算上限。"""

from __future__ import annotations


class BudgetController:
    """预算控制器：监控 Agent 执行成本。

    check() 状态机：spent < 80%（可调）→ "ok"；80%~上限 → "warning"；≥ 上限 →
    "exceeded"。
    """

    def __init__(self, max_budget_usd: float, warn_threshold: float = 0.8) -> None:
        self.max_budget_usd = max_budget_usd
        self.warn_threshold = warn_threshold
        self.spent_usd: float = 0.0
        self.total_tokens: int = 0

    def record(self, cost_usd: float = 0.0, tokens: int = 0) -> str:
        """累计一次计量（LLM 回调的 token/成本），返回最新状态。"""
        self.spent_usd += cost_usd
        self.total_tokens += tokens
        return self.check()

    def check(self) -> str:
        """检查当前预算状态，返回 ``"ok" | "warning" | "exceeded"``。"""
        if self.max_budget_usd <= 0:
            return "ok"
        if self.spent_usd >= self.max_budget_usd:
            return "exceeded"
        if self.spent_usd >= self.max_budget_usd * self.warn_threshold:
            return "warning"
        return "ok"
