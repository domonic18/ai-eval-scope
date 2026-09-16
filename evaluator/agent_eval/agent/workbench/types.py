"""会话机数据类型 — WorkbenchAgentConfig 可调参数与 TurnResult 单轮结果。"""

from __future__ import annotations

from dataclasses import dataclass, field

from agent_eval.agent.workbench.sut_probe import PROBE_TIMEOUT_S, TOOL_BUDGETS


@dataclass(frozen=True, slots=True)
class WorkbenchAgentConfig:
    """会话机可调参数（tunables 单点载体）。

    默认值是安全阀不是天花板；CLI 旗标
    （``--max-turns/--max-segments/--budget-usd``）以本对象为同一载体注入。
    """

    max_turns: int = 40  # 单段安全阀基数（recursion_limit = max_turns × 2，非任务预算）
    max_fix_rounds: int = 3  # 校验门禁回改轮上限
    max_segments: int = 3  # 自动分段续跑上限（撞线即开新段直到此数）
    budget_usd: float | None = None  # 会话预算（None = 不启用）
    max_dialogue_entries: int = 40  # 持久化的对话条数上限（防跨会话无限膨胀）
    resume_max_entries: int = 24  # 续作注入上下文的最多条数
    resume_max_chars: int = 400  # 续作注入单条截断
    # 探测域档位默认（域 = 工具面 + 提示词段 + 门禁策略，域档位可覆盖）
    probe_budgets: dict[str, int] = field(default_factory=lambda: dict(TOOL_BUDGETS))
    probe_timeout_s: float = PROBE_TIMEOUT_S


@dataclass
class TurnResult:
    """单轮会话结果（宿主据此渲染与续轮）。"""

    reply: str  # Agent 计划/总结文本
    diff: str  # 暂存 vs 磁盘统一 diff
    staged: bool  # 本轮是否产生了暂存变更
    committed: bool = False  # 是否已落盘
    committed_files: list[str] = field(default_factory=list)
    validation_errors: list[str] = field(default_factory=list)  # 最终仍未修复的错误
    aborted_reason: str = ""  # 用户放弃 / 轮次耗尽等
