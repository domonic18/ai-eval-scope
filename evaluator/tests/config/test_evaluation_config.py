"""评估引擎默认参数配置测试。"""

from __future__ import annotations

from agent_eval.config import (
    EVALUATOR_DEFAULTS,
    METRIC_THRESHOLDS,
    PIPELINE_DEFAULTS,
    SCORE_AGGREGATION_WEIGHTS,
)


class TestMetricThresholds:
    """指标通过阈值默认参数测试。"""

    def test_thresholds(self) -> None:
        """阈值与报告/orchestrator 中保持一致。"""
        assert METRIC_THRESHOLDS.dr == 0.95
        assert METRIC_THRESHOLDS.cpr == 0.90
        assert METRIC_THRESHOLDS.avg_reward == 0.70


class TestScoreAggregationWeights:
    """Reward 聚合权重默认参数测试。"""

    def test_dimension_weights(self) -> None:
        """维度乘数默认值。"""
        assert SCORE_AGGREGATION_WEIGHTS.w3 == 1.0
        assert SCORE_AGGREGATION_WEIGHTS.w4 == 1.0

    def test_format_penalty(self) -> None:
        """格式门控奖惩值。"""
        assert SCORE_AGGREGATION_WEIGHTS.format_pass == 1.0
        assert SCORE_AGGREGATION_WEIGHTS.format_fail == -3.0

    def test_commonsense_penalty(self) -> None:
        """常识门控奖惩值。"""
        assert SCORE_AGGREGATION_WEIGHTS.commonsense_pass == 1.0
        assert SCORE_AGGREGATION_WEIGHTS.commonsense_fail == 0.0

    def test_soft_weights(self) -> None:
        """软约束内部权重和为 1。"""
        weights = SCORE_AGGREGATION_WEIGHTS.soft_weights
        assert sum(weights.values()) == 1.0
        assert "soft.teaching_logic" in weights
        assert "soft.content_diversity" in weights

    def test_pref_weights(self) -> None:
        """偏好约束内部权重和约为 1。"""
        weights = SCORE_AGGREGATION_WEIGHTS.pref_weights
        assert round(sum(weights.values()), 2) == 1.0
        assert "pref.style_preference" in weights
        assert "pref.depth_preference" in weights
        assert "pref.request_fulfillment" in weights

    def test_vision_soft_weights(self) -> None:
        """with_vision=True 时默认软约束权重和约为 1。"""
        weights = SCORE_AGGREGATION_WEIGHTS.vision_soft_weights
        assert round(sum(weights.values()), 2) == 1.0
        assert "soft.teaching_logic" in weights
        assert "soft.content_diversity" in weights
        assert "vision.quality" in weights


class TestPipelineDefaults:
    """PipelineEngine 默认参数测试。"""

    def test_short_circuit_policy(self) -> None:
        """默认短路策略。"""
        assert PIPELINE_DEFAULTS.short_circuit_policy == "fail_fast"

    def test_reward_weights(self) -> None:
        """Reward 聚合默认权重。"""
        assert PIPELINE_DEFAULTS.reward_weights == {"w3": 1.0, "w4": 1.0}


class TestEvaluatorDefaults:
    """评估器默认行为参数测试。"""

    def test_llm_degrade_score(self) -> None:
        """LLM 不可用时降级分数。"""
        assert EVALUATOR_DEFAULTS.llm_degrade_score == 0.7

    def test_max_content_chars(self) -> None:
        """文本 LLM 评估默认最大内容字符数。"""
        assert EVALUATOR_DEFAULTS.max_content_chars == 8000

    def test_arith_context_window(self) -> None:
        """算术错误检测上下文窗口。"""
        assert EVALUATOR_DEFAULTS.arith_context_window == 40

    def test_logical_consistency_threshold(self) -> None:
        """逻辑一致性通过阈值。"""
        assert EVALUATOR_DEFAULTS.logical_consistency_pass_threshold == 0.6

    def test_allowed_formats(self) -> None:
        """文件格式检查默认允许格式。"""
        assert EVALUATOR_DEFAULTS.allowed_formats == ["md", "html"]

    def test_llm_judge_pass_threshold(self) -> None:
        """LLM Judge 归一化分数通过阈值。"""
        assert EVALUATOR_DEFAULTS.llm_judge_pass_threshold == 0.4

    def test_arith_tolerance(self) -> None:
        """算术/等式验证默认容差。"""
        assert EVALUATOR_DEFAULTS.arith_tolerance == 0.01

    def test_llm_judge_content_chars(self) -> None:
        """LLM Judge prompt content 默认最大字符数。"""
        assert EVALUATOR_DEFAULTS.llm_judge_content_chars == 4000

    def test_llm_judge_combined_content_chars(self) -> None:
        """多文件 LLM Judge 组合文本默认最大字符数。"""
        assert EVALUATOR_DEFAULTS.llm_judge_combined_content_chars == 6000

    def test_max_file_chars(self) -> None:
        """单文件文本截断默认最大字符数。"""
        assert EVALUATOR_DEFAULTS.max_file_chars == 4000

    def test_vision_quality_dimensions(self) -> None:
        """视觉质量评估默认维度与权重。"""
        dims = EVALUATOR_DEFAULTS.vision_quality_dimensions
        assert len(dims) == 4
        ids = [d[0] for d in dims]
        assert "layout" in ids
        assert "color_scheme" in ids
        assert "information_hierarchy" in ids
        assert "readability" in ids
        assert sum(d[2] for d in dims) == 1.0

    def test_text_collection_patterns(self) -> None:
        """文本收集默认扫描的文档扩展名。"""
        patterns = EVALUATOR_DEFAULTS.text_collection_patterns
        assert "*.md" in patterns
        assert "*.html" in patterns
        assert "*.htm" in patterns
