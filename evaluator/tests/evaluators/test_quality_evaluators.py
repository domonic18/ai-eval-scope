"""质量评估器测试 — LLM Judge 评估器。"""

from __future__ import annotations

from pathlib import Path
from typing import Any
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
        assert result.score == 0.0
        assert result.status == EvalStatus.SKIP
        assert "跳过" in result.reason

    def test_degradation_no_evidence_dir(self, tmp_path: Path) -> None:
        """无 evidence_dir 时降级模式。"""
        sample = _prepare_output(tmp_path, "Content")
        evaluator = TeachingLogicEvaluator()
        result = evaluator.evaluate(sample, {"judge_orchestrator": MagicMock()})
        assert result.score == 0.0
        assert result.status == EvalStatus.SKIP

    def test_llm_quota_exceeded_skips(self, tmp_path: Path) -> None:
        """LLM 额度耗尽时 SKIP（不计分、不 FAIL）。"""
        from agent_eval.core.exceptions import LLMQuotaExceededError

        sample = _prepare_output(tmp_path, "内容" * 50)
        mock_orch = MagicMock()
        mock_orch.judge.side_effect = LLMQuotaExceededError("额度耗尽")
        result = TeachingLogicEvaluator().evaluate(
            sample, {"judge_orchestrator": mock_orch, "evidence_dir": tmp_path / "ev"}
        )
        assert result.status == EvalStatus.SKIP
        assert result.score == 0.0
        assert "Quota" in result.reason

    def test_llm_network_error_skips(self, tmp_path: Path) -> None:
        """LLM 网络错误时 SKIP（不计分）。"""
        from agent_eval.core.exceptions import LLMNetworkError

        sample = _prepare_output(tmp_path, "内容" * 50)
        mock_orch = MagicMock()
        mock_orch.judge.side_effect = LLMNetworkError("超时")
        result = TeachingLogicEvaluator().evaluate(
            sample, {"judge_orchestrator": mock_orch, "evidence_dir": tmp_path / "ev"}
        )
        assert result.status == EvalStatus.SKIP
        assert "Network" in result.reason

    def test_llm_auth_error_skips(self, tmp_path: Path) -> None:
        """LLM 鉴权失败时 SKIP。"""
        from agent_eval.core.exceptions import LLMAuthError

        sample = _prepare_output(tmp_path, "内容" * 50)
        mock_orch = MagicMock()
        mock_orch.judge.side_effect = LLMAuthError("401")
        result = TeachingLogicEvaluator().evaluate(
            sample, {"judge_orchestrator": mock_orch, "evidence_dir": tmp_path / "ev"}
        )
        assert result.status == EvalStatus.SKIP
        assert "Auth" in result.reason

    def test_quota_exceeded_sets_circuit_breaker(self, tmp_path: Path) -> None:
        """额度耗尽时设置熔断标志（同 context 后续评估器可据此跳过）。"""
        from agent_eval.core.exceptions import LLMQuotaExceededError

        sample = _prepare_output(tmp_path, "内容" * 50)
        mock_orch = MagicMock()
        mock_orch.judge.side_effect = LLMQuotaExceededError("额度耗尽")
        ctx = {"judge_orchestrator": mock_orch, "evidence_dir": tmp_path / "ev"}
        TeachingLogicEvaluator().evaluate(sample, ctx)
        assert ctx.get("llm_quota_exhausted") is True

    def test_circuit_breaker_skips_subsequent(self, tmp_path: Path) -> None:
        """熔断标志已设置时，评估器直接 SKIP（不调用 LLM）。"""
        sample = _prepare_output(tmp_path, "内容" * 50)
        mock_orch = MagicMock()
        ctx = {
            "judge_orchestrator": mock_orch,
            "evidence_dir": tmp_path / "ev",
            "llm_quota_exhausted": True,
        }
        result = TeachingLogicEvaluator().evaluate(sample, ctx)
        assert result.status == EvalStatus.SKIP
        assert "熔断" in result.reason
        mock_orch.judge.assert_not_called()

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
            assert result.score == 0.0
            assert result.status == EvalStatus.SKIP
            assert "跳过" in result.reason


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
        """12 项评估器全部注册。"""
        expected = [
            # 格式（2）
            "format.response_format",
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
        assert len(expected) == 12
        for eval_id in expected:
            e = registry.create(eval_id, {})
            assert e is not None, f"评估器 {eval_id} 未注册"


def _make_e2e_mock_orchestrator() -> MagicMock:
    """构造一个可响应所有 LLM Judge 模板的 Mock Orchestrator。"""
    dimensions_by_template: dict[str, list[tuple[str, str, float]]] = {
        "pedagogical_logic": [
            ("structure", "结构完整性", 0.4),
            ("progression", "知识递进", 0.3),
            ("engagement", "互动设计", 0.3),
        ],
        "content_diversity": [
            ("media_variety", "媒体多样性", 0.4),
            ("topic_breadth", "主题广度", 0.3),
            ("example_richness", "示例丰富度", 0.3),
        ],
        "style_preference": [
            ("language_style", "语言风格", 0.4),
            ("formatting", "排版风格", 0.3),
            ("tone", "语气风格", 0.3),
        ],
        "depth_preference": [
            ("knowledge_depth", "知识深度", 0.4),
            ("detail_level", "细节程度", 0.3),
            ("rigor", "严谨程度", 0.3),
        ],
        "request_fulfillment": [
            ("completeness", "完整性", 0.4),
            ("relevance", "相关性", 0.3),
            ("quality", "质量", 0.3),
        ],
        "logical_consistency": [
            ("internal_consistency", "内部一致性", 0.5),
            ("causal_logic", "因果逻辑", 0.3),
            ("classification_logic", "分类逻辑", 0.2),
        ],
        "info_accuracy": [
            ("factual_correctness", "事实验证", 0.6),
            ("statement_accuracy", "陈述准确性", 0.4),
        ],
    }

    def _make_dim(dim_id: str, name: str, weight: float) -> MagicMock:
        d = MagicMock()
        d.dim_id = dim_id
        d.name = name
        d.weight = weight
        return d

    def _judge_side_effect(*args: Any, **kwargs: Any) -> tuple[dict[str, float], MagicMock]:
        template_id = kwargs.get("template_id", "unknown")
        dims = dimensions_by_template.get(template_id, [])
        scores = {dim_id: 8.0 for dim_id, _, _ in dims} if dims else {"score": 8.0}

        record = MagicMock()
        record.judge_id = f"judge_{template_id}_001"
        record.provider_name = "deepseek_judge"
        record.model = "deepseek-chat"
        record.confidence = {k: "high" for k in scores}
        record.summary = f"{template_id} 评估总结：表现良好。"
        record.raw_response = {"summary": record.summary}
        return scores, record

    def _templates_get(template_id: str) -> MagicMock | None:
        dims = dimensions_by_template.get(template_id)
        if dims is None:
            return None
        template = MagicMock()
        template.dimensions = [_make_dim(*d) for d in dims]
        return template

    mock_orch = MagicMock()
    mock_orch.judge.side_effect = _judge_side_effect
    mock_orch.templates.get.side_effect = _templates_get
    return mock_orch


class TestFullCascadeEndToEnd:
    """端到端三阶段级联测试：format → commonsense → quality 全部执行。"""

    def _build_package(self, tmp_path: Path) -> Path:
        """构造一个可通过格式/常识门控的 ExecutionPackage 目录。"""
        pkg = tmp_path / "package"
        pkg.mkdir(parents=True)
        output = pkg / "output"
        output.mkdir(parents=True)
        # 有效的 Markdown + HTML 文件
        (output / "index.md").write_text(
            "# 一元一次方程\n\n"
            "本节课学习一元一次方程的解法。\n\n"
            "## 教学目标\n"
            "- 理解一元一次方程的概念\n"
            "- 掌握移项、合并同类项的方法\n\n"
            "## 例题\n"
            "解方程 $2x + 4 = 10$。\n"
            "移项得 $2x = 6$，所以 $x = 3$。\n",
            encoding="utf-8",
        )
        (output / "guide.html").write_text(
            "<html><body><h1>学习指南</h1><p>请先阅读教材，再完成练习。</p></body></html>",
            encoding="utf-8",
        )
        return pkg

    def test_full_cascade_all_stages_execute(self, tmp_path: Path) -> None:
        """默认管线完整执行三阶段， quality 阶段 LLM Judge 结果带溯源。"""
        from agent_eval.evaluation.engine import build_default_pipeline

        pkg = self._build_package(tmp_path)
        engine = build_default_pipeline(registry)
        mock_orch = _make_e2e_mock_orchestrator()
        evidence_dir = tmp_path / "evidence"
        evidence_dir.mkdir()

        result = engine.evaluate_sample(
            pkg,
            {
                "sample_id": "e2e_sample",
                "judge_orchestrator": mock_orch,
                "evidence_dir": evidence_dir,
                "task_input": {"title": "一元一次方程", "subject": "数学"},
            },
        )

        # 三阶段均执行（未被短路）
        assert "format" in result.stage_results
        assert "commonsense" in result.stage_results
        assert "quality" in result.stage_results

        # 格式门控通过
        assert result.stage_results["format"].status == EvalStatus.PASS
        assert result.stage_results["format"].gate_passed is True

        # quality 阶段包含 5 个 LLM Judge 评估器结果
        quality_results = result.stage_results["quality"].constraint_results
        assert len(quality_results) == 5
        expected_ids = {
            "soft.teaching_logic",
            "soft.content_diversity",
            "pref.style_preference",
            "pref.depth_preference",
            "pref.request_fulfillment",
        }
        actual_ids = {cr.constraint_id for cr in quality_results}
        assert actual_ids == expected_ids

        # LLM Judge 溯源字段完整
        for cr in quality_results:
            assert cr.judge_provider == "deepseek_judge"
            assert cr.judge_model == "deepseek-chat"
            assert cr.judge_record_path is not None
            assert cr.judge_record_path.startswith("evidence/")

        # 评分聚合正确计算
        assert result.s_format == 1.0
        assert result.s_common == 1.0
        assert result.s_soft > 0.0
        assert result.s_pref > 0.0
        assert result.reward > 0.0

    def test_full_cascade_short_circuit_on_format_fail(self, tmp_path: Path) -> None:
        """格式门控失败时 commonsense/quality 被 SKIP。"""
        from agent_eval.evaluation.engine import build_default_pipeline

        pkg = tmp_path / "package"
        pkg.mkdir()
        output = pkg / "output"
        output.mkdir()
        # 非法格式：txt 文件
        (output / "bad.txt").write_text("not valid format", encoding="utf-8")

        engine = build_default_pipeline(registry)
        mock_orch = _make_e2e_mock_orchestrator()

        result = engine.evaluate_sample(
            pkg,
            {
                "sample_id": "e2e_short_circuit",
                "judge_orchestrator": mock_orch,
                "evidence_dir": tmp_path / "ev",
            },
        )

        assert result.stage_results["format"].status == EvalStatus.FAIL
        assert result.stage_results["commonsense"].status == EvalStatus.SKIP
        assert result.stage_results["quality"].status == EvalStatus.SKIP
        assert result.s_format == -3.0
        # 短路后 soft/pref 得 0 分
        assert result.s_soft == 0.0
        assert result.s_pref == 0.0

    def test_full_cascade_metrics_report(self, tmp_path: Path) -> None:
        """批量评估可产出 MetricsReport，且指标计算正确。"""
        from agent_eval.evaluation.engine import build_default_pipeline

        pkg1 = self._build_package(tmp_path / "pkg1")
        pkg2 = self._build_package(tmp_path / "pkg2")
        engine = build_default_pipeline(registry)
        mock_orch = _make_e2e_mock_orchestrator()
        evidence_dir = tmp_path / "evidence"
        evidence_dir.mkdir()

        report = engine.evaluate_batch(
            [pkg1, pkg2],
            extra_context={
                "judge_orchestrator": mock_orch,
                "evidence_dir": evidence_dir,
                "task_input": {"title": "一元一次方程", "subject": "数学"},
            },
            run_id="e2e_run",
        )

        assert report.total_samples == 2
        assert report.dr == 1.0
        assert report.cpr == 1.0
        assert report.avg_reward > 0.0
        assert report.run_id == "e2e_run"
