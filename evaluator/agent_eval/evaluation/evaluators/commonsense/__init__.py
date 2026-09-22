"""常识约束评估器（3 项）— HARD_SCORE。

- commonsense.info_accuracy: 知识准确性（FACT_VERIFY，规则 + fact_verdict 二次确认 + LLM）
- commonsense.chronological_order: 时序正确性（LLM_JUDGE，评整个课件）
- commonsense.logical_consistency: 逻辑一致性（LLM_JUDGE，评整个课件）

结构：info_accuracy 三层检查按 Phase 拆为组合 mixin（_builtin_checks /
_rule_checks / _llm_verify），info_accuracy.py 为组合主体；本包 ``__init__``
统一再导出（导入即完成注册）。math_formula / unit_consistency 已移除
（前者易误报且 info_accuracy 已覆盖算术检查，后者为死代码）。
"""

from __future__ import annotations

from agent_eval.evaluation.evaluators.commonsense.consistency import (
    LogicalConsistencyEvaluator,
)
from agent_eval.evaluation.evaluators.commonsense.info_accuracy import (
    InfoAccuracyEvaluator,
)
from agent_eval.evaluation.evaluators.commonsense.order import ChronologicalOrderEvaluator

__all__ = [
    "ChronologicalOrderEvaluator",
    "InfoAccuracyEvaluator",
    "LogicalConsistencyEvaluator",
]
