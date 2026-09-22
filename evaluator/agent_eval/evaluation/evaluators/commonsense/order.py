"""commonsense.chronological_order 评估器 — LLM 评时序正确性。"""

from __future__ import annotations

from agent_eval.config import EVALUATOR_DEFAULTS
from agent_eval.core.types import ConstraintTier, EvalMethod
from agent_eval.evaluation.evaluators.quality_evaluators import BaseLLMJudgeEvaluator
from agent_eval.evaluation.registry import registry


@registry.register("commonsense.chronological_order")
class ChronologicalOrderEvaluator(BaseLLMJudgeEvaluator):
    """时序正确性检查 — LLM 评审整个课件的时间线/序号/步骤顺序合理性。

    旧规则实现（提取年份/序号但不校验，始终 PASS）已废弃；改为 LLM-as-judge，
    对整个课件文本评估时序一致性。LLM 不可用时降级 SKIP（不计分）。
    """

    evaluator_id = "commonsense.chronological_order"
    name = "时序正确性检查"
    tier = ConstraintTier.HARD_SCORE
    method = EvalMethod.LLM_JUDGE
    template_id = "chronological_order"
    pass_threshold = EVALUATOR_DEFAULTS.logical_consistency_pass_threshold
    # 时序是跨模块全局语义（整个课件的时间线/步骤顺序），保持整单元单次评估
    default_granularity = "package"
