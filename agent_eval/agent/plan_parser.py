"""EvalPlanLoader — Markdown 评测计划解析器。

解析 Markdown 格式的评测计划（YAML frontmatter + Markdown 正文），
提取结构化元数据和自然语言策略描述。
后续迭代实现，当前为骨架文件。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class EvalPlan:
    """评测计划数据模型。"""

    plan_id: str
    version: str
    target: str
    max_turns: int
    budget_usd: float
    body: str  # Markdown 正文原文

    def to_system_prompt(self) -> str:
        """将评测计划转换为 Agent system prompt 片段。"""
        header = (
            f"## 评测计划: {self.plan_id} (v{self.version})\n"
            f"- 评测目标: {self.target}\n"
            f"- 最大轮次: {self.max_turns}\n"
            f"- 预算上限: ${self.budget_usd:.2f}\n\n"
        )
        return header + self.body


class EvalPlanLoader:
    """Markdown 评测计划解析器。

    解析格式：
        ---
        plan_id: <string>
        version: <string>
        target: <string>
        max_turns: <int>
        budget_usd: <float>
        ---
        # Markdown 正文...

    注意：本类将在后续迭代中完整实现。当前仅提供接口骨架。
    """

    @staticmethod
    def load(plan_path: Path | str) -> EvalPlan:
        """从 Markdown 文件加载评测计划。

        Args:
            plan_path: 评测计划文件路径。

        Returns:
            解析后的 EvalPlan 对象。

        Raises:
            NotImplementedError: 当前迭代尚未实现。
        """
        raise NotImplementedError("EvalPlanLoader.load() 将在后续迭代中实现。")

    @staticmethod
    def parse(content: str) -> EvalPlan:
        """从字符串解析评测计划。

        Args:
            content: Markdown 评测计划内容。

        Returns:
            解析后的 EvalPlan 对象。

        Raises:
            NotImplementedError: 当前迭代尚未实现。
        """
        raise NotImplementedError("EvalPlanLoader.parse() 将在后续迭代中实现。")
