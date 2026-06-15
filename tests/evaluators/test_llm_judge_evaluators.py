"""LLM Judge 评估器补充测试 — 覆盖加权归一化、模板加载、评分阈值、变量构建。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

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


def _make_mock_orchestrator(
    scores: dict[str, float],
    *,
    num_dims: int = 3,
    summary: str = "LLM 评估总结：内容质量良好。",
    dim_names: list[str] | None = None,
):
    """创建一个模拟的 JudgeOrchestrator，返回指定分数。"""
    mock_record = MagicMock()
    mock_record.judge_id = "judge_test_001"
    mock_record.provider_name = "deepseek_judge"
    mock_record.model = "deepseek-chat"
    mock_record.confidence = {k: "high" for k in scores}
    mock_record.summary = summary

    mock_orch = MagicMock()
    mock_orch.judge.return_value = (scores, mock_record)

    # 构建带权重和名称的维度
    default_weights = [0.4, 0.3, 0.3][:num_dims]
    dim_ids = list(scores.keys())
    if dim_names is None:
        dim_names = [f"维度_{dim_ids[i]}" for i in range(num_dims)]
    mock_template = MagicMock()
    mock_dims = []
    for i in range(num_dims):
        d = MagicMock()
        d.dim_id = dim_ids[i]
        d.name = dim_names[i] if i < len(dim_names) else f"维度_{dim_ids[i]}"
        d.weight = default_weights[i] if i < len(default_weights) else 1.0
        mock_dims.append(d)
    mock_template.dimensions = mock_dims
    mock_orch.templates.get.return_value = mock_template
    return mock_orch


# ─── 1. 生产模板加载与渲染 ───


class TestProductionTemplates:
    """验证 assets/prompts/ 下的 5 个生产模板全部可加载、可渲染。"""

    @pytest.fixture
    def prompts_dir(self) -> Path:
        return Path(__file__).resolve().parent.parent.parent / "assets" / "prompts"

    @pytest.mark.parametrize(
        "template_id",
        [
            "pedagogical_logic",
            "content_diversity",
            "style_preference",
            "depth_preference",
            "request_fulfillment",
        ],
    )
    def test_template_loadable(self, prompts_dir: Path, template_id: str) -> None:
        """模板可加载。"""
        from agent_eval.llm.judge.template_manager import TemplateManager

        mgr = TemplateManager(prompts_dir)
        mgr.load_all()
        template = mgr.get(template_id)
        assert template is not None
        assert len(template.dimensions) >= 2
        assert template.system_prompt
        assert template.user_prompt_template

    @pytest.mark.parametrize(
        "template_id,variables",
        [
            ("pedagogical_logic", {"title": "方程", "content": "x+1=2", "subject": "数学"}),
            (
                "content_diversity",
                {
                    "title": "方程",
                    "content": "x+1=2",
                    "subject": "数学",
                    "has_formula": "是",
                    "has_table": "否",
                    "has_image": "否",
                    "has_list": "是",
                },
            ),
            ("style_preference", {"title": "方程", "content": "x+1=2", "subject": "数学"}),
            ("depth_preference", {"title": "方程", "content": "x+1=2", "subject": "数学"}),
            (
                "request_fulfillment",
                {
                    "content": "x+1=2",
                    "original_request": "生成方程课件",
                    "expected_output": "完整教案",
                },
            ),
        ],
    )
    def test_template_renderable(
        self, prompts_dir: Path, template_id: str, variables: dict
    ) -> None:
        """模板可渲染（变量完整）。"""
        from agent_eval.llm.judge.template_manager import TemplateManager

        mgr = TemplateManager(prompts_dir)
        mgr.load_all()
        sys_prompt, user_prompt = mgr.render(template_id, variables)
        assert sys_prompt
        assert len(user_prompt) > 10

    def test_template_dimensions_valid(self, prompts_dir: Path) -> None:
        """所有模板维度权重之和为 1.0。"""
        from agent_eval.llm.judge.template_manager import TemplateManager

        mgr = TemplateManager(prompts_dir)
        mgr.load_all()
        for tid in mgr.template_ids:
            template = mgr.get(tid)
            total_weight = sum(d.weight for d in template.dimensions)
            assert abs(total_weight - 1.0) < 0.01, f"模板 {tid} 权重之和为 {total_weight}，不为 1.0"


# ─── 2. 加权分数归一化 ───


class TestWeightedScoreNormalization:
    """验证 LLM Judge 评估器的加权分数归一化。"""

    def test_high_scores(self, tmp_path: Path) -> None:
        """高分 → 归一化后约 0.8。"""
        sample = _prepare_output(tmp_path, "# 方程\n" + "教学内容。" * 20)
        mock_orch = _make_mock_orchestrator(
            {"structure": 8.0, "progression": 8.0, "engagement": 8.0}
        )
        evaluator = TeachingLogicEvaluator()
        result = evaluator.evaluate(
            sample, {"judge_orchestrator": mock_orch, "evidence_dir": tmp_path / "ev"}
        )
        # (8*0.4 + 8*0.3 + 8*0.3) / 1.0 / 10 = 0.8
        assert abs(result.score - 0.8) < 0.01

    def test_low_scores_below_threshold(self, tmp_path: Path) -> None:
        """低分 → score < 0.4 → FAIL。"""
        sample = _prepare_output(tmp_path, "# 方程\n" + "教学内容。" * 20)
        mock_orch = _make_mock_orchestrator(
            {"structure": 2.0, "progression": 1.0, "engagement": 1.0}
        )
        evaluator = TeachingLogicEvaluator()
        result = evaluator.evaluate(
            sample, {"judge_orchestrator": mock_orch, "evidence_dir": tmp_path / "ev"}
        )
        # (2*0.4 + 1*0.3 + 1*0.3) / 10 = 0.14
        assert result.score < 0.4
        assert result.status == EvalStatus.FAIL

    def test_mixed_scores(self, tmp_path: Path) -> None:
        """混合分数 → 加权计算正确。"""
        sample = _prepare_output(tmp_path, "# 方程\n" + "教学内容。" * 20)
        mock_orch = _make_mock_orchestrator(
            {"structure": 6.0, "progression": 5.0, "engagement": 3.0}
        )
        evaluator = TeachingLogicEvaluator()
        result = evaluator.evaluate(
            sample, {"judge_orchestrator": mock_orch, "evidence_dir": tmp_path / "ev"}
        )
        # (6*0.4 + 5*0.3 + 3*0.3) / 10 = (2.4 + 1.5 + 0.9) / 10 = 0.48
        assert abs(result.score - 0.48) < 0.01
        assert result.status == EvalStatus.PASS  # 0.48 >= 0.4

    def test_perfect_score(self, tmp_path: Path) -> None:
        """满分 10 → 归一化 1.0。"""
        sample = _prepare_output(tmp_path, "# 方程\n" + "教学内容。" * 20)
        mock_orch = _make_mock_orchestrator(
            {"structure": 10.0, "progression": 10.0, "engagement": 10.0}
        )
        evaluator = TeachingLogicEvaluator()
        result = evaluator.evaluate(
            sample, {"judge_orchestrator": mock_orch, "evidence_dir": tmp_path / "ev"}
        )
        assert result.score == 1.0

    def test_zero_score(self, tmp_path: Path) -> None:
        """零分 → 归一化 0.0。"""
        sample = _prepare_output(tmp_path, "# 方程\n" + "教学内容。" * 20)
        mock_orch = _make_mock_orchestrator(
            {"structure": 0.0, "progression": 0.0, "engagement": 0.0}
        )
        evaluator = TeachingLogicEvaluator()
        result = evaluator.evaluate(
            sample, {"judge_orchestrator": mock_orch, "evidence_dir": tmp_path / "ev"}
        )
        assert result.score == 0.0
        assert result.status == EvalStatus.FAIL


# ─── 3. 溯源字段验证 ───


class TestTracingFields:
    """验证 ConstraintResult 中的 Judge 溯源字段。"""

    def test_judge_fields_filled(self, tmp_path: Path) -> None:
        """LLM 评估成功时溯源字段完整。"""
        sample = _prepare_output(tmp_path, "# 方程\n" + "教学内容。" * 20)
        mock_orch = _make_mock_orchestrator(
            {"structure": 7.0, "progression": 6.0, "engagement": 5.0}
        )
        evaluator = TeachingLogicEvaluator()
        result = evaluator.evaluate(
            sample, {"judge_orchestrator": mock_orch, "evidence_dir": tmp_path / "ev"}
        )
        assert result.judge_provider == "deepseek_judge"
        assert result.judge_model == "deepseek-chat"
        assert result.judge_record_path == "evidence/judge_test_001.json"

    def test_judge_fields_none_in_degradation(self, tmp_path: Path) -> None:
        """降级模式时溯源字段为 None。"""
        sample = _prepare_output(tmp_path, "内容" * 50)
        evaluator = TeachingLogicEvaluator()
        result = evaluator.evaluate(sample, {})
        assert result.judge_provider is None
        assert result.judge_model is None
        assert result.judge_record_path is None

    def test_details_contain_scores(self, tmp_path: Path) -> None:
        """details 中包含各维度分数和置信度。"""
        sample = _prepare_output(tmp_path, "# 方程\n" + "教学内容。" * 20)
        mock_orch = _make_mock_orchestrator(
            {"structure": 7.0, "progression": 6.0, "engagement": 5.0}
        )
        evaluator = TeachingLogicEvaluator()
        result = evaluator.evaluate(
            sample, {"judge_orchestrator": mock_orch, "evidence_dir": tmp_path / "ev"}
        )
        assert result.details is not None
        assert "scores" in result.details
        assert result.details["scores"]["structure"] == 7.0
        assert "confidence" in result.details


# ─── 4. 各评估器 _build_variables 差异化 ───


class TestBuildVariables:
    """验证各 LLM 评估器的模板变量构建。"""

    def test_teaching_logic_basic_vars(self) -> None:
        """教学逻辑 — 基础变量。"""
        evaluator = TeachingLogicEvaluator()
        variables = evaluator._build_variables(
            "课件内容",
            {
                "task_input": {"title": "方程", "subject": "数学"},
            },
        )
        assert variables["content"] == "课件内容"
        assert variables["title"] == "方程"
        assert variables["subject"] == "数学"

    def test_content_diversity_media_detection_formula(self) -> None:
        """内容多样性 — 公式检测。"""
        evaluator = ContentDiversityEvaluator()
        variables = evaluator._build_variables("$E=mc^2$", {})
        assert variables["has_formula"] == "是"

    def test_content_diversity_media_detection_table(self) -> None:
        """内容多样性 — 表格检测（Markdown）。"""
        evaluator = ContentDiversityEvaluator()
        variables = evaluator._build_variables("| a | b |\n|---|---|", {})
        assert variables["has_table"] == "是"

    def test_content_diversity_media_detection_html_table(self) -> None:
        """内容多样性 — 表格检测（HTML）。"""
        evaluator = ContentDiversityEvaluator()
        variables = evaluator._build_variables("<table><tr><td>1</td></tr></table>", {})
        assert variables["has_table"] == "是"

    def test_content_diversity_media_detection_image(self) -> None:
        """内容多样性 — 图片检测。"""
        evaluator = ContentDiversityEvaluator()
        variables = evaluator._build_variables("![图](img.png)", {})
        assert variables["has_image"] == "是"

    def test_content_diversity_media_detection_none(self) -> None:
        """内容多样性 — 无任何媒体。"""
        evaluator = ContentDiversityEvaluator()
        variables = evaluator._build_variables("纯文字内容", {})
        assert variables["has_formula"] == "否"
        assert variables["has_table"] == "否"
        assert variables["has_image"] == "否"
        assert variables["has_list"] == "否"

    def test_request_fulfillment_with_task_input(self) -> None:
        """需求满足度 — 从 task_input 提取需求。"""
        evaluator = RequestFulfillmentEvaluator()
        variables = evaluator._build_variables(
            "课件内容",
            {
                "task_input": {"input": "生成数学课件", "expected": "完整教案"},
            },
        )
        assert variables["original_request"] == "生成数学课件"
        assert variables["expected_output"] == "完整教案"

    def test_request_fulfillment_no_task_input(self) -> None:
        """需求满足度 — 无 task_input 时使用默认值。"""
        evaluator = RequestFulfillmentEvaluator()
        variables = evaluator._build_variables("课件内容", {})
        assert variables["original_request"] == "未提供原始需求"
        assert variables["expected_output"] == "未提供预期输出描述"

    def test_content_truncation(self, tmp_path: Path) -> None:
        """内容超过 max_content_chars 时截断。"""
        long_content = "x" * 10000
        sample = _prepare_output(tmp_path, long_content)
        mock_orch = _make_mock_orchestrator(
            {"structure": 5.0, "progression": 5.0, "engagement": 5.0}
        )
        evaluator = TeachingLogicEvaluator()
        result = evaluator.evaluate(
            sample,
            {
                "judge_orchestrator": mock_orch,
                "evidence_dir": tmp_path / "ev",
                "max_content_chars": 100,
            },
        )
        # 应该正常执行，不会因内容过长而失败
        assert result.status in (EvalStatus.PASS, EvalStatus.FAIL)


# ─── 5. 内容截断与边界 ───


class TestEdgeCases:
    """边界条件测试。"""

    def test_exactly_threshold_score(self, tmp_path: Path) -> None:
        """score 恰好等于阈值 0.4 → PASS。"""
        sample = _prepare_output(tmp_path, "# 方程\n" + "教学内容。" * 20)
        # (4*0.4 + 4*0.3 + 4*0.3) / 10 = 0.4
        mock_orch = _make_mock_orchestrator(
            {"structure": 4.0, "progression": 4.0, "engagement": 4.0}
        )
        evaluator = TeachingLogicEvaluator()
        result = evaluator.evaluate(
            sample, {"judge_orchestrator": mock_orch, "evidence_dir": tmp_path / "ev"}
        )
        assert abs(result.score - 0.4) < 0.01
        assert result.status == EvalStatus.PASS  # 0.4 >= 0.4

    def test_no_template_dimensions(self, tmp_path: Path) -> None:
        """无维度信息时取平均。"""
        sample = _prepare_output(tmp_path, "# 方程\n" + "教学内容。" * 20)
        mock_record = MagicMock()
        mock_record.judge_id = "judge_test"
        mock_record.provider_name = "ds"
        mock_record.model = "m"
        mock_record.confidence = {}
        mock_record.summary = "无维度模板的评估总结。"

        mock_orch = MagicMock()
        mock_orch.judge.return_value = ({"a": 6.0, "b": 8.0}, mock_record)
        mock_orch.templates.get.return_value = MagicMock(dimensions=[])  # 无维度

        evaluator = TeachingLogicEvaluator()
        result = evaluator.evaluate(
            sample, {"judge_orchestrator": mock_orch, "evidence_dir": tmp_path / "ev"}
        )
        # (6 + 8) / 2 / 10 = 0.7
        assert abs(result.score - 0.7) < 0.01

    def test_llm_error_includes_message(self, tmp_path: Path) -> None:
        """LLM 调用错误时 reason 包含错误信息。"""
        sample = _prepare_output(tmp_path, "内容" * 50)
        mock_orch = MagicMock()
        mock_orch.judge.side_effect = RuntimeError("Connection timeout")

        evaluator = TeachingLogicEvaluator()
        result = evaluator.evaluate(
            sample, {"judge_orchestrator": mock_orch, "evidence_dir": tmp_path / "ev"}
        )
        assert result.status == EvalStatus.ERROR
        assert "Connection timeout" in result.reason
        assert result.score == 0.0

    def test_all_five_evaluators_method(self) -> None:
        """所有 5 个 LLM 评估器 method 为 LLM_JUDGE。"""
        for eval_id in [
            "soft.teaching_logic",
            "soft.content_diversity",
            "pref.style_preference",
            "pref.depth_preference",
            "pref.request_fulfillment",
        ]:
            evaluator = registry.create(eval_id, {})
            assert evaluator.method == EvalMethod.LLM_JUDGE, f"{eval_id} method 不对"


# ─── 6. 可解释性测试 ───


class TestExplainability:
    """验证 LLM Judge 评估结果的可解释性。"""

    def test_reason_contains_dimension_names(self, tmp_path: Path) -> None:
        """reason 包含维度中文名。"""
        sample = _prepare_output(tmp_path, "# 方程\n" + "教学内容。" * 20)
        mock_orch = _make_mock_orchestrator(
            {"structure": 6.0, "progression": 5.0, "engagement": 3.0},
            dim_names=["结构完整性", "知识递进", "互动设计"],
        )
        evaluator = TeachingLogicEvaluator()
        result = evaluator.evaluate(
            sample, {"judge_orchestrator": mock_orch, "evidence_dir": tmp_path / "ev"}
        )
        assert "结构完整性" in result.reason
        assert "知识递进" in result.reason
        assert "互动设计" in result.reason

    def test_reason_contains_summary(self, tmp_path: Path) -> None:
        """reason 包含 LLM summary 摘要。"""
        sample = _prepare_output(tmp_path, "# 方程\n" + "教学内容。" * 20)
        mock_orch = _make_mock_orchestrator(
            {"structure": 6.0, "progression": 5.0, "engagement": 3.0},
            summary="教学结构基本完整，但互动环节不足。",
        )
        evaluator = TeachingLogicEvaluator()
        result = evaluator.evaluate(
            sample, {"judge_orchestrator": mock_orch, "evidence_dir": tmp_path / "ev"}
        )
        assert "教学结构基本完整" in result.reason

    def test_reason_truncates_long_summary(self, tmp_path: Path) -> None:
        """过长的 summary 在 reason 中被截断到 150 字符。"""
        sample = _prepare_output(tmp_path, "# 方程\n" + "教学内容。" * 20)
        long_summary = "这是一段很长的评价。" * 100
        mock_orch = _make_mock_orchestrator(
            {"structure": 6.0, "progression": 5.0, "engagement": 3.0},
            summary=long_summary,
        )
        evaluator = TeachingLogicEvaluator()
        result = evaluator.evaluate(
            sample, {"judge_orchestrator": mock_orch, "evidence_dir": tmp_path / "ev"}
        )
        # reason 中 summary 部分不超过 150 字符
        summary_in_reason = result.reason.split(" — ")[-1] if " — " in result.reason else ""
        assert len(summary_in_reason) <= 155  # 150 + 略微余量

    def test_details_contains_dimensions_structure(self, tmp_path: Path) -> None:
        """details 包含结构化维度详情（id, name, score, weight, confidence）。"""
        sample = _prepare_output(tmp_path, "# 方程\n" + "教学内容。" * 20)
        mock_orch = _make_mock_orchestrator(
            {"structure": 8.0, "progression": 7.0, "engagement": 6.0},
            dim_names=["结构完整性", "知识递进", "互动设计"],
        )
        evaluator = TeachingLogicEvaluator()
        result = evaluator.evaluate(
            sample, {"judge_orchestrator": mock_orch, "evidence_dir": tmp_path / "ev"}
        )
        assert "dimensions" in result.details
        dims = result.details["dimensions"]
        assert len(dims) == 3
        assert dims[0]["id"] == "structure"
        assert dims[0]["name"] == "结构完整性"
        assert dims[0]["score"] == 8.0
        assert dims[0]["weight"] == 0.4
        assert dims[0]["confidence"] == "high"

    def test_details_contains_full_summary(self, tmp_path: Path) -> None:
        """details 包含完整的 LLM summary（不截断）。"""
        sample = _prepare_output(tmp_path, "# 方程\n" + "教学内容。" * 20)
        full_summary = "这是一个详细的评价总结，包含了多个方面的分析。" * 10
        mock_orch = _make_mock_orchestrator(
            {"structure": 6.0, "progression": 5.0, "engagement": 3.0},
            summary=full_summary,
        )
        evaluator = TeachingLogicEvaluator()
        result = evaluator.evaluate(
            sample, {"judge_orchestrator": mock_orch, "evidence_dir": tmp_path / "ev"}
        )
        assert "summary" in result.details
        assert result.details["summary"] == full_summary

    def test_degradation_reason_unchanged(self, tmp_path: Path) -> None:
        """降级模式 reason 保持不变（无 summary）。"""
        sample = _prepare_output(tmp_path, "内容" * 50)
        evaluator = TeachingLogicEvaluator()
        result = evaluator.evaluate(sample, {})
        assert "降级" in result.reason
        assert "LLM 评估" not in result.reason
        assert "dimensions" not in result.details

    def test_no_summary_graceful(self, tmp_path: Path) -> None:
        """record 无 summary 时 reason 不报错（不追加 summary）。"""
        sample = _prepare_output(tmp_path, "# 方程\n" + "教学内容。" * 20)
        mock_orch = _make_mock_orchestrator(
            {"structure": 6.0, "progression": 5.0, "engagement": 3.0},
            summary="",  # 空 summary
        )
        evaluator = TeachingLogicEvaluator()
        result = evaluator.evaluate(
            sample, {"judge_orchestrator": mock_orch, "evidence_dir": tmp_path / "ev"}
        )
        # reason 不应包含 " — " 分隔符（因为 summary 为空）
        assert " — " not in result.reason
