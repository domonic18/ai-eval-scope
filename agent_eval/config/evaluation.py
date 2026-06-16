"""评估引擎默认参数配置。

集中管理评估指标阈值、评分聚合权重、评估器默认行为等与评估业务规则
相关的默认值，避免散落在 evaluation/、reporting/、orchestrator/ 等模块中。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class MetricThresholds:
    """汇总报告中的指标通过阈值。

    这些阈值用于判断一次评估运行是否达到交付/质量目标，并在 report_generator
    和 orchestrator 中保持一致。
    """

    # 交付率（Delivery Rate）：格式门控通过样本比例
    dr: float = 0.95
    # 约束通过率（Constraint Pass Rate）：格式 + 常识双门控通过样本比例
    cpr: float = 0.90
    # 平均 Reward：所有样本 Reward 的平均值
    avg_reward: float = 0.70


@dataclass(frozen=True)
class ScoreAggregationWeights:
    """Reward 聚合公式中的权重与惩罚值。

    Reward = S_format + S_common + w3 × S_soft + w4 × S_pref
    """

    # 软约束维度乘数
    w3: float = 1.0
    # 偏好约束维度乘数
    w4: float = 1.0
    # 格式门控全通过时的 S_format 得分
    format_pass: float = 1.0
    # 格式门控任一失败时的 S_format 惩罚
    format_fail: float = -3.0
    # 常识门控全通过时的 S_common 得分
    commonsense_pass: float = 1.0
    # 常识门控任一失败时的 S_common 得分
    commonsense_fail: float = 0.0
    # 软约束内部各评估器权重
    soft_weights: dict[str, float] = field(
        default_factory=lambda: {
            "soft.teaching_logic": 0.5,
            "soft.content_diversity": 0.5,
        }
    )
    # 偏好约束内部各评估器权重
    pref_weights: dict[str, float] = field(
        default_factory=lambda: {
            "pref.style_preference": 0.33,
            "pref.depth_preference": 0.33,
            "pref.request_fulfillment": 0.34,
        }
    )
    # with_vision=True 时 PipelineEngine 的默认软约束权重
    vision_soft_weights: dict[str, float] = field(
        default_factory=lambda: {
            "soft.teaching_logic": 0.4,
            "soft.content_diversity": 0.3,
            "vision.quality": 0.3,
        }
    )


@dataclass(frozen=True)
class PipelineDefaults:
    """PipelineEngine 默认参数。"""

    # 各阶段默认短路策略
    short_circuit_policy: str = "fail_fast"
    # Reward 聚合默认权重
    reward_weights: dict[str, float] = field(default_factory=lambda: {"w3": 1.0, "w4": 1.0})


@dataclass(frozen=True)
class EvaluatorDefaults:
    """各评估器默认行为参数。"""

    # LLM 不可用时（无 Provider/无配置）的默认降级分数
    llm_degrade_score: float = 0.7
    # 文本 LLM 评估时默认最大内容字符数（超过则截断）
    max_content_chars: int = 8000
    # 算术错误检测时的上下文窗口大小（字符数）
    arith_context_window: int = 40
    # 逻辑一致性检查：0-10 分制转换为 0-1 后的通过阈值
    logical_consistency_pass_threshold: float = 0.6
    # 文件格式检查默认允许格式
    allowed_formats: list[str] = field(default_factory=lambda: ["md", "html"])
    # LLM Judge 归一化分数通过阈值（0-1）
    llm_judge_pass_threshold: float = 0.4
    # 算术/等式验证容差
    arith_tolerance: float = 0.01
    # 视觉质量评估默认维度（dim_id, display_name, weight）
    vision_quality_dimensions: list[tuple[str, str, float]] = field(
        default_factory=lambda: [
            ("layout", "排版", 0.3),
            ("color_scheme", "配色", 0.25),
            ("information_hierarchy", "信息层级", 0.25),
            ("readability", "可读性", 0.2),
        ]
    )
    # 文本收集时默认扫描的文档扩展名（glob 模式）
    text_collection_patterns: list[str] = field(
        default_factory=lambda: ["*.md", "*.markdown", "*.html", "*.htm"]
    )


# 模块级单例
METRIC_THRESHOLDS = MetricThresholds()
SCORE_AGGREGATION_WEIGHTS = ScoreAggregationWeights()
PIPELINE_DEFAULTS = PipelineDefaults()
EVALUATOR_DEFAULTS = EvaluatorDefaults()
