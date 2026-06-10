"""评估器实现 — 导入各评估器模块以触发注册。"""

# 导入格式评估器（4 项）
# 导入常识评估器（5 项）
from agent_eval.evaluation.evaluators.commonsense_evaluators import (  # noqa: F401
    ChronologicalOrderEvaluator,
    InfoAccuracyEvaluator,
    LogicalConsistencyEvaluator,
    MathFormulaEvaluator,
    UnitConsistencyEvaluator,
)
from agent_eval.evaluation.evaluators.format_evaluators import (  # noqa: F401
    DocumentCountEvaluator,
    HtmlValidityEvaluator,
    ResponseFormatEvaluator,
    StructureComplianceEvaluator,
)

# 导入质量评估器（7 项：2 Rule-based + 5 LLM Judge）
from agent_eval.evaluation.evaluators.quality_evaluators import (  # noqa: F401
    BaseLLMJudgeEvaluator,
    ContentDensityEvaluator,
    ContentDiversityEvaluator,
    DepthPreferenceEvaluator,
    RequestFulfillmentEvaluator,
    StylePreferenceEvaluator,
    TeachingLogicEvaluator,
    VisualConsistencyEvaluator,
)

__all__ = [
    # 格式评估器
    "ResponseFormatEvaluator",
    "DocumentCountEvaluator",
    "StructureComplianceEvaluator",
    "HtmlValidityEvaluator",
    # 常识评估器
    "InfoAccuracyEvaluator",
    "ChronologicalOrderEvaluator",
    "LogicalConsistencyEvaluator",
    "MathFormulaEvaluator",
    "UnitConsistencyEvaluator",
    # 质量评估器（Rule-based）
    "ContentDensityEvaluator",
    "VisualConsistencyEvaluator",
    # 质量评估器（LLM Judge）
    "BaseLLMJudgeEvaluator",
    "TeachingLogicEvaluator",
    "ContentDiversityEvaluator",
    "StylePreferenceEvaluator",
    "DepthPreferenceEvaluator",
    "RequestFulfillmentEvaluator",
]
