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
    # 格式门控任一失败时的 S_format 得分（0 = 不得分）。
    # format 的重要性由 DR（格式通过率）+ fail-fast 短路体现，不再用负值惩罚——
    # 保证 reward 归一化到 [0,1]、无负值（行业最佳实践）。
    format_fail: float = 0.0
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
    # LLM Judge prompt 变量中 content 字段的默认最大字符数
    llm_judge_content_chars: int = 4000
    # 多文件 LLM Judge（如 info_accuracy）组合文本默认最大字符数
    llm_judge_combined_content_chars: int = 6000
    # 单文件文本截断默认最大字符数（如 info_accuracy per-file）
    max_file_chars: int = 4000
    # 视觉质量评估默认维度（dim_id, display_name, weight）
    vision_quality_dimensions: list[tuple[str, str, float]] = field(
        default_factory=lambda: [
            ("layout", "排版", 0.3),
            ("color_scheme", "配色", 0.25),
            ("information_hierarchy", "信息层级", 0.25),
            ("readability", "可读性", 0.2),
        ]
    )
    # 视觉截图渲染单页超时（毫秒）。SCF/容器等受限环境需比 Playwright 默认 30s 更宽容，
    # 否则 full_page 截超长课件页易超时（见 renderer PlaywrightScreenshotRenderer）。
    vision_screenshot_timeout_ms: int = 60_000
    # 内容完整性检查：判定「空壳文件」的相对阈值 — 剥标签正文低于包内中位数的该比例
    # （且无媒体元素）判为疑似空占位。相对比例而非绝对字数，跨学段/学科/页面类型自适应。
    content_empty_body_ratio: float = 0.15
    # 内容完整性检查：视为「实质内容」的媒体元素（存在任一即不判空，如图片型课件页）
    content_media_tags: list[str] = field(
        default_factory=lambda: ["img", "table", "video", "audio", "svg", "canvas", "iframe"]
    )
    # ─── 判定专线（decision 角色）高置信误触过滤（commonsense.info_accuracy 规则候选预筛）───
    # filter-only 语义：判定专线只有剔除权、无确认权，真错误的裁定与解释一律由 LLM
    # fact_verdict 产出。以上各项均可被规则集 params 覆盖（同 fact_verdict_batch_size）。
    # 功能总开关（默认关——合入零行为变化）
    decision_enabled: bool = False
    # P(真错误) 低于此值判高置信误触 → 剔除。0.50 为对拍校准值（误触带 ≤0.29 /
    # 真错误带 ≥0.79 空谷定标，勿回退 0.10）；阈值或模型变更须重跑对拍
    decision_drop_below: float = 0.50
    # Noul 并发上限（官方限流 1200 req/min，保守取值）
    decision_max_concurrency: int = 8
    # 单次 Noul 请求超时（秒）——建 decision 线路客户端时覆写 ProviderConfig.timeout_sec
    # （判定要求快失败；瞬时重试由 DecisionClient 内部承担）
    decision_timeout_sec: float = 10.0
    # 问题正文覆盖（None=内置默认；仅替换 instructions，criteria 双侧定义固定）
    decision_question_template: str | None = None
    # fact_verdict 分批复核的批间并发上限（1=串行；批间无顺序依赖，verdicts 按
    # 自带 index 键控合并）。候选 > 单批容量时多批才并发，减少整段复核墙钟时间。
    fact_verdict_max_concurrency: int = 1


# 模块级单例
METRIC_THRESHOLDS = MetricThresholds()
SCORE_AGGREGATION_WEIGHTS = ScoreAggregationWeights()
PIPELINE_DEFAULTS = PipelineDefaults()
EVALUATOR_DEFAULTS = EvaluatorDefaults()
