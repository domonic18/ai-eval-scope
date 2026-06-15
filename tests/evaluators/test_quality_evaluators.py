"""质量评估器测试 — LLM Judge 评估器。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from agent_eval.core.types import ConstraintTier, EvalMethod, EvalStatus
from agent_eval.evaluation.evaluators.quality_evaluators import (
    ContentDiversityEvaluator,
    DepthPreferenceEvaluator,
    RequestFulfillmentEvaluator,
    StylePreferenceEvaluator,
    TeachingLogicEvaluator,
)
from agent_eval.evaluation.models import ConstraintResult
from agent_eval.evaluation.registry import registry

FIXTURES = Path(__file__).parent.parent / "fixtures"


def _prepare_output(tmp_path: Path, content: str = "", filename: str = "index.md") -> Path:
    """准备 output 目录。"""
    output = tmp_path / "output"
    output.mkdir()
    (output / filename).write_text(content, encoding="utf-8")
    return tmp_path


# ─── LLM Judge Evaluators ───


class TestBaseLLMJudgeEvaluator:
    """LLM Judge 评估器基类测试。"""

    def test_degradation_mode(self, tmp_path: Path) -> None:
        """无 orchestrator 时降级模式。"""
        sample = _prepare_output(tmp_path, "# Test\nSome content here.")
        evaluator = TeachingLogicEvaluator()
        result = evaluator.evaluate(sample, {})  # 无 judge_orchestrator
        assert result.score == 0.7
        assert result.status == EvalStatus.PASS
        assert "降级" in result.reason

    def test_degradation_no_evidence_dir(self, tmp_path: Path) -> None:
        """无 evidence_dir 时降级模式。"""
        sample = _prepare_output(tmp_path, "Content")
        evaluator = TeachingLogicEvaluator()
        result = evaluator.evaluate(sample, {"judge_orchestrator": MagicMock()})
        assert result.score == 0.7

    def test_llm_empty_content(self, tmp_path: Path) -> None:
        """空文档 LLM 评估失败。"""
        sample = _prepare_output(tmp_path, "")
        evaluator = TeachingLogicEvaluator()
        mock_orch = MagicMock()
        result = evaluator.evaluate(
            sample,
            {"judge_orchestrator": mock_orch, "evidence_dir": tmp_path / "ev"},
        )
        assert result.status == EvalStatus.FAIL
        assert result.score == 0.0


class TestTeachingLogicEvaluator:
    """教学逻辑评估器测试。"""

    def test_registered(self) -> None:
        evaluator = registry.create("soft.teaching_logic", {})
        assert isinstance(evaluator, TeachingLogicEvaluator)
        assert evaluator.method == EvalMethod.LLM_JUDGE
        assert evaluator.template_id == "pedagogical_logic"

    def test_llm_judge_success(self, tmp_path: Path) -> None:
        """LLM Judge 成功评估。"""
        sample = _prepare_output(tmp_path, "# 一元一次方程\n" + "教学内容。" * 50)
        mock_record = MagicMock()
        mock_record.judge_id = "judge_test"
        mock_record.provider_name = "deepseek_judge"
        mock_record.model = "deepseek-chat"
        mock_record.confidence = {"structure": "high", "progression": "high", "engagement": "high"}
        mock_record.summary = "教学结构完整，知识递进合理，但互动设计不足。"
        mock_orch = MagicMock()
        mock_orch.judge.return_value = (
            {"structure": 8.0, "progression": 7.5, "engagement": 7.0},
            mock_record,
        )
        mock_template = MagicMock()
        dim1 = MagicMock()
        dim1.dim_id = "structure"
        dim1.name = "结构完整性"
        dim1.weight = 0.4
        dim2 = MagicMock()
        dim2.dim_id = "progression"
        dim2.name = "知识递进"
        dim2.weight = 0.3
        dim3 = MagicMock()
        dim3.dim_id = "engagement"
        dim3.name = "互动设计"
        dim3.weight = 0.3
        mock_template.dimensions = [dim1, dim2, dim3]
        mock_orch.templates.get.return_value = mock_template

        evaluator = TeachingLogicEvaluator()
        result = evaluator.evaluate(
            sample,
            {"judge_orchestrator": mock_orch, "evidence_dir": tmp_path / "ev"},
        )
        assert isinstance(result, ConstraintResult)
        assert result.judge_provider == "deepseek_judge"
        assert result.judge_model == "deepseek-chat"
        assert result.judge_record_path is not None
        assert result.score > 0.5
        # 可解释性：reason 包含维度中文名
        assert "结构完整性" in result.reason
        assert "知识递进" in result.reason
        # 可解释性：reason 包含 LLM summary
        assert "教学结构完整" in result.reason
        # 可解释性：details 包含 dimensions 结构
        assert "dimensions" in result.details
        assert result.details["dimensions"][0]["name"] == "结构完整性"
        assert result.details["dimensions"][0]["weight"] == 0.4
        # 可解释性：details 包含 summary
        assert "summary" in result.details
        assert "教学结构完整" in result.details["summary"]

    def test_llm_judge_error(self, tmp_path: Path) -> None:
        """LLM Judge 调用失败。"""
        sample = _prepare_output(tmp_path, "内容" * 100)
        mock_orch = MagicMock()
        mock_orch.judge.side_effect = Exception("API error")

        evaluator = TeachingLogicEvaluator()
        result = evaluator.evaluate(
            sample,
            {"judge_orchestrator": mock_orch, "evidence_dir": tmp_path / "ev"},
        )
        assert result.status == EvalStatus.ERROR
        assert "API error" in result.reason


class TestContentDiversityEvaluator:
    """内容多样性评估器测试。"""

    def test_registered(self) -> None:
        evaluator = registry.create("soft.content_diversity", {})
        assert isinstance(evaluator, ContentDiversityEvaluator)
        assert evaluator.template_id == "content_diversity"

    def test_build_variables_includes_media(self, tmp_path: Path) -> None:
        """变量包含媒体检测信息。"""
        content = "# Test\n$E=mc^2$\n\n| a | b |\n\n![img](x.png)\n\n- item"
        evaluator = ContentDiversityEvaluator()
        variables = evaluator._build_variables(content, {})
        assert variables["has_formula"] == "是"
        assert variables["has_table"] == "是"
        assert variables["has_image"] == "是"
        assert variables["has_list"] == "是"


class TestPreferenceEvaluators:
    """偏好约束评估器测试。"""

    def test_style_registered(self) -> None:
        e = registry.create("pref.style_preference", {})
        assert isinstance(e, StylePreferenceEvaluator)
        assert e.tier == ConstraintTier.PREFERENCE
        assert e.template_id == "style_preference"

    def test_depth_registered(self) -> None:
        e = registry.create("pref.depth_preference", {})
        assert isinstance(e, DepthPreferenceEvaluator)
        assert e.tier == ConstraintTier.PREFERENCE
        assert e.template_id == "depth_preference"

    def test_fulfillment_registered(self) -> None:
        e = registry.create("pref.request_fulfillment", {})
        assert isinstance(e, RequestFulfillmentEvaluator)
        assert e.tier == ConstraintTier.PREFERENCE
        assert e.template_id == "request_fulfillment"

    def test_fulfillment_variables(self, tmp_path: Path) -> None:
        """需求满足度变量包含原始需求。"""
        evaluator = RequestFulfillmentEvaluator()
        variables = evaluator._build_variables(
            "content",
            {"task_input": {"input": "生成课件", "expected": "完整教案"}},
        )
        assert variables["original_request"] == "生成课件"
        assert variables["expected_output"] == "完整教案"

    def test_all_preference_degradation(self, tmp_path: Path) -> None:
        """所有偏好评估器降级模式。"""
        sample = _prepare_output(tmp_path, "内容" * 100)
        for eval_id in [
            "pref.style_preference",
            "pref.depth_preference",
            "pref.request_fulfillment",
        ]:
            evaluator = registry.create(eval_id, {})
            result = evaluator.evaluate(sample, {})
            assert result.score == 0.7
            assert "降级" in result.reason


# ─── 三阶段级联集成测试 ───


class TestThreeStageCascade:
    """三阶段级联集成测试（format → commonsense → quality）。"""

    def test_full_pipeline_quality_stage(self, tmp_path: Path) -> None:
        """quality 阶段可执行 LLM Judge 评估器。"""
        from agent_eval.evaluation.engine import build_default_pipeline

        engine = build_default_pipeline(registry)
        # 验证 quality 阶段包含评估器
        quality_stage = [s for s in engine.stages if s.stage_id == "quality"]
        assert len(quality_stage) == 1
        assert len(quality_stage[0].evaluators) == 5  # 5 llm

    def test_17_evaluators_registered(self) -> None:
        """14 项评估器全部注册。"""
        expected = [
            # 格式（4）
            "format.response_format",
            "format.document_count",
            "format.structure_compliance",
            "format.html_validity",
            # 常识（5）
            "commonsense.info_accuracy",
            "commonsense.chronological_order",
            "commonsense.logical_consistency",
            "commonsense.math_formula",
            "commonsense.unit_consistency",
            # 软约束（2）
            "soft.teaching_logic",
            "soft.content_diversity",
            # 偏好约束（3）
            "pref.style_preference",
            "pref.depth_preference",
            "pref.request_fulfillment",
        ]
        assert len(expected) == 14
        for eval_id in expected:
            e = registry.create(eval_id, {})
            assert e is not None, f"评估器 {eval_id} 未注册"
