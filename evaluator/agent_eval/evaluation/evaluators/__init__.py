"""评估器实现 — 导入各评估器模块以触发注册。"""

# 导入格式评估器（4 项）
# 导入常识评估器（3 项）
from agent_eval.evaluation.evaluators.commonsense_evaluators import (  # noqa: F401
    ChronologicalOrderEvaluator,
    InfoAccuracyEvaluator,
    LogicalConsistencyEvaluator,
)
from agent_eval.evaluation.evaluators.format_evaluators import (  # noqa: F401
    HtmlValidityEvaluator,
    ResponseFormatEvaluator,
)

# 自动发现插件评估器（plugins/ 目录下的 .py 文件）
from agent_eval.evaluation.evaluators.plugins import discover_plugins  # noqa: F401

# 导入质量评估器（5 项 LLM Judge）
from agent_eval.evaluation.evaluators.quality_evaluators import (  # noqa: F401
    BaseLLMJudgeEvaluator,
    ContentDiversityEvaluator,
    DepthPreferenceEvaluator,
    RequestFulfillmentEvaluator,
    StylePreferenceEvaluator,
    TeachingLogicEvaluator,
)

# 导入视觉评估器（opt-in，--enable-vision 时使用）
from agent_eval.evaluation.evaluators.vision_evaluators import (  # noqa: F401
    VisionQualityEvaluator,
)

discover_plugins()

__all__ = [
    # 格式评估器
    "ResponseFormatEvaluator",
    "HtmlValidityEvaluator",
    # 常识评估器
    "InfoAccuracyEvaluator",
    "ChronologicalOrderEvaluator",
    "LogicalConsistencyEvaluator",
    # 质量评估器（LLM Judge）
    "BaseLLMJudgeEvaluator",
    "TeachingLogicEvaluator",
    "ContentDiversityEvaluator",
    "StylePreferenceEvaluator",
    "DepthPreferenceEvaluator",
    "RequestFulfillmentEvaluator",
    # 视觉评估器
    "VisionQualityEvaluator",
]
