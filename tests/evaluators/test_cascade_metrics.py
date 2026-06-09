"""级联控制、评分聚合、指标计算测试。"""

from pathlib import Path

import pytest

from agent_eval.core.types import ConstraintTier, EvalMethod, EvalStatus
from agent_eval.evaluation.aggregator import ScoreAggregator
from agent_eval.evaluation.base import BaseEvaluator
from agent_eval.evaluation.engine import PipelineConfig, StageConfig, EvaluatorConfig, PipelineEngine
from agent_eval.evaluation.evaluators import *  # trigger registration
from agent_eval.evaluation.metrics import MetricsCalculator
from agent_eval.evaluation.models import ConstraintResult, SampleResult, StageResult
from agent_eval.evaluation.registry import EvaluatorRegistry, registry
from agent_eval.evaluation.stage import PipelineStage

FIXTURES = Path(__file__).parent.parent / "fixtures"
GOLDEN = FIXTURES / "golden"


# ─── PipelineStage 测试 ───


class TestPipelineStage:
    def test_all_pass(self) -> None:
        """所有评估器通过时，gate_passed = True。"""
        stage = PipelineStage("format", [], "fail_fast")
        result = stage.execute(Path("/tmp/nonexistent"), {})
        assert result.gate_passed is True
        assert result.status == EvalStatus.PASS

    def test_hard_gate_fail_stops(self, tmp_path: Path) -> None:
        """HARD_GATE 评估器失败时，fail_fast 模式立即终止。"""
        output = tmp_path / "output"
        output.mkdir()
        (output / "bad.txt").write_text("bad content")

        ev = registry.create("format.response_format", {"allowed_formats": ["md"]})
        stage = PipelineStage("format", [ev], "fail_fast")
        result = stage.execute(tmp_path, {})

        assert result.gate_passed is False
        assert result.status == EvalStatus.FAIL

    def test_continue_all_runs_all(self, tmp_path: Path) -> None:
        """continue_all 模式下，即使失败也继续执行后续评估器。"""
        output = tmp_path / "output"
        output.mkdir()
        (output / "bad.txt").write_text("bad")

        ev1 = registry.create("format.response_format", {"allowed_formats": ["md"]})
        ev2 = registry.create("format.document_count", {"min": 5, "max": 10})

        stage = PipelineStage("format", [ev1, ev2], "continue_all")
        result = stage.execute(tmp_path, {})

        assert result.gate_passed is False
        # 两个评估器都应执行
        assert len(result.constraint_results) == 2

    def test_evaluator_exception_handled(self) -> None:
        """评估器抛出异常时不中断，标记为 ERROR。"""

        class FailingEvaluator(BaseEvaluator):
            evaluator_id = "test.failing"
            name = "Failing"
            tier = ConstraintTier.HARD_GATE
            method = EvalMethod.RULE

            def evaluate(self, sample, context):
                raise RuntimeError("boom")

        stage = PipelineStage("test", [FailingEvaluator()], "fail_fast")
        result = stage.execute(None, {})

        assert result.gate_passed is False
        assert result.constraint_results[0].status == EvalStatus.ERROR


# ─── ScoreAggregator 测试 ───


class TestScoreAggregator:
    def _make_sample(
        self,
        fmt_status: EvalStatus = EvalStatus.PASS,
        fmt_passed: bool = True,
        com_status: EvalStatus = EvalStatus.PASS,
        com_passed: bool = True,
        soft_score: float = 0.0,
        pref_score: float = 0.0,
    ) -> SampleResult:
        """辅助：构造 SampleResult。"""
        result = SampleResult(sample_id="test", status=EvalStatus.PASS)

        result.stage_results["format"] = StageResult(
            stage_id="format",
            status=fmt_status,
            gate_passed=fmt_passed,
        )
        result.stage_results["commonsense"] = StageResult(
            stage_id="commonsense",
            status=com_status,
            gate_passed=com_passed,
        )
        result.stage_results["quality"] = StageResult(
            stage_id="quality",
            status=EvalStatus.PASS,
            constraint_results=[
                ConstraintResult(
                    constraint_id="soft.content_density",
                    name="密度",
                    tier=ConstraintTier.SOFT,
                    status=EvalStatus.PASS,
                    score=soft_score,
                ),
                ConstraintResult(
                    constraint_id="pref.style_preference",
                    name="风格",
                    tier=ConstraintTier.PREFERENCE,
                    status=EvalStatus.PASS,
                    score=pref_score,
                ),
            ],
        )
        return result

    def test_all_pass(self) -> None:
        # Use explicit weights that match only the constraint_ids present in results.
        # This makes the calculation deterministic:
        #   soft_weights: {"soft.content_density": 1.0} => wtotal=1.0, wsum=1.0*0.8=0.8
        #   pref_weights: {"pref.style_preference": 1.0} => wtotal=1.0, wsum=1.0*0.7=0.7
        #   reward = 1.0 + 1.0 + 1.0*0.8 + 1.0*0.7 = 3.5
        agg = ScoreAggregator(
            w3=1.0,
            w4=1.0,
            soft_weights={"soft.content_density": 1.0},
            pref_weights={"pref.style_preference": 1.0},
        )
        sample = self._make_sample(soft_score=0.8, pref_score=0.7)
        score = agg.aggregate(sample)

        assert score.s_format == 1.0
        assert score.s_common == 1.0
        assert score.reward == pytest.approx(1.0 + 1.0 + 1.0 * 0.8 + 1.0 * 0.7, abs=0.01)

    def test_format_fail(self) -> None:
        agg = ScoreAggregator()
        sample = self._make_sample(fmt_status=EvalStatus.FAIL, fmt_passed=False)
        score = agg.aggregate(sample)
        assert score.s_format == -3.0

    def test_commonsense_fail(self) -> None:
        agg = ScoreAggregator()
        sample = self._make_sample(com_status=EvalStatus.FAIL, com_passed=False)
        score = agg.aggregate(sample)
        assert score.s_common == 0.0

    def test_format_skip(self) -> None:
        agg = ScoreAggregator()
        sample = self._make_sample(fmt_status=EvalStatus.SKIP, fmt_passed=False)
        score = agg.aggregate(sample)
        assert score.s_format == 0.0

    def test_reward_formula(self) -> None:
        """手动验证: Reward = 1 + 1 + 1*0.78 + 1*0.65 = 3.43"""
        agg = ScoreAggregator(
            w3=1.0,
            w4=1.0,
            soft_weights={"soft.content_density": 1.0},
            pref_weights={"pref.style_preference": 1.0},
        )
        sample = self._make_sample(soft_score=0.78, pref_score=0.65)
        score = agg.aggregate(sample)
        assert score.reward == pytest.approx(3.43, abs=0.01)

    def test_custom_weights(self) -> None:
        agg = ScoreAggregator(
            w3=0.5,
            w4=0.5,
            soft_weights={"soft.content_density": 1.0},
            pref_weights={"pref.style_preference": 1.0},
        )
        sample = self._make_sample(soft_score=1.0, pref_score=1.0)
        score = agg.aggregate(sample)
        # Reward = 1 + 1 + 0.5*1.0 + 0.5*1.0 = 3.0
        assert score.reward == pytest.approx(3.0, abs=0.01)


# ─── MetricsCalculator 测试 ───


class TestMetricsCalculator:
    def _make_result(
        self,
        sample_id: str = "s001",
        fmt_passed: bool = True,
        com_passed: bool = True,
        reward: float = 2.0,
        duration_ms: float = 1000.0,
    ) -> SampleResult:
        r = SampleResult(
            sample_id=sample_id,
            status=EvalStatus.PASS if fmt_passed else EvalStatus.FAIL,
            reward=reward,
            total_duration_ms=duration_ms,
        )
        r.stage_results["format"] = StageResult(
            stage_id="format",
            status=EvalStatus.PASS if fmt_passed else EvalStatus.FAIL,
            gate_passed=fmt_passed,
        )
        r.stage_results["commonsense"] = StageResult(
            stage_id="commonsense",
            status=EvalStatus.PASS if com_passed else EvalStatus.FAIL,
            gate_passed=com_passed,
        )
        return r

    def test_all_pass(self) -> None:
        calc = MetricsCalculator()
        results = [self._make_result(f"s{i}", reward=2.0 + i * 0.1) for i in range(5)]
        report = calc.compute(results, run_id="run_001")

        assert report.total_samples == 5
        assert report.dr == 1.0
        assert report.cpr == 1.0
        assert report.avg_reward == pytest.approx(2.2, abs=0.01)

    def test_mixed_results(self) -> None:
        calc = MetricsCalculator()
        results = [
            self._make_result("s1", fmt_passed=True, com_passed=True),
            self._make_result("s2", fmt_passed=True, com_passed=False),
            self._make_result("s3", fmt_passed=False, com_passed=False),
            self._make_result("s4", fmt_passed=True, com_passed=True),
        ]
        report = calc.compute(results)

        assert report.dr == 0.75  # 3/4
        assert report.cpr == 0.5  # 2/4

    def test_empty_results(self) -> None:
        calc = MetricsCalculator()
        report = calc.compute([])
        assert report.total_samples == 0

    def test_failure_breakdown(self) -> None:
        calc = MetricsCalculator()
        r = self._make_result("s1", fmt_passed=False, reward=0.0)
        r.stage_results["format"].constraint_results.append(
            ConstraintResult(
                constraint_id="format.response_format",
                name="格式",
                tier=ConstraintTier.HARD_GATE,
                status=EvalStatus.FAIL,
                score=0.0,
            )
        )
        report = calc.compute([r])
        assert "format.response_format" in report.failure_breakdown

    def test_cond_r(self) -> None:
        calc = MetricsCalculator()
        results = [
            self._make_result("s1", fmt_passed=True, com_passed=True, reward=3.0),
            self._make_result("s2", fmt_passed=True, com_passed=True, reward=2.0),
            self._make_result("s3", fmt_passed=False, reward=-1.0),  # 不通过门控
        ]
        report = calc.compute(results)
        # CondR = (3.0 + 2.0) / 2 = 2.5
        assert report.cond_r == pytest.approx(2.5, abs=0.01)


# ─── PipelineEngine 端到端测试 ───


class TestPipelineEngine:
    def test_valid_documents_pass(self, tmp_path: Path) -> None:
        """合法文档集通过格式门控，S_format = +1。"""
        output = tmp_path / "output"
        output.mkdir()
        (output / "index.md").write_text("# 一元一次方程\n\n## 定义\n\n内容。\n")
        (output / "chapter.md").write_text("# 练习\n\n## 基础\n\n2+3=5\n")

        config = PipelineConfig(
            stages=[
                StageConfig(
                    id="format",
                    short_circuit_policy="fail_fast",
                    evaluators=[
                        EvaluatorConfig("format.response_format", {"allowed_formats": ["md"]}),
                        EvaluatorConfig("format.document_count", {"min": 1, "max": 10}),
                        EvaluatorConfig("format.structure_compliance"),
                    ],
                ),
            ]
        )
        engine = PipelineEngine(config, registry)
        result = engine.evaluate_sample(tmp_path, {"sample_id": "test_001"})

        assert result.s_format == 1.0
        assert result.stage_results["format"].gate_passed is True

    def test_invalid_format_short_circuits(self, tmp_path: Path) -> None:
        """格式不合法文档被门控拦截，后续阶段 SKIP。"""
        output = tmp_path / "output"
        output.mkdir()
        (output / "data.csv").write_text("bad")

        config = PipelineConfig(
            stages=[
                StageConfig(
                    id="format",
                    short_circuit_policy="fail_fast",
                    evaluators=[
                        EvaluatorConfig("format.response_format", {"allowed_formats": ["md"]}),
                    ],
                ),
                StageConfig(
                    id="commonsense",
                    short_circuit_policy="fail_fast",
                    evaluators=[
                        EvaluatorConfig("commonsense.info_accuracy"),
                    ],
                ),
            ]
        )
        engine = PipelineEngine(config, registry)
        result = engine.evaluate_sample(tmp_path, {"sample_id": "test_002"})

        assert result.s_format == -3.0
        # 常识阶段应被 SKIP
        assert result.stage_results.get("commonsense") is not None
        assert result.stage_results["commonsense"].status == EvalStatus.SKIP

    def test_golden_valid_docset(self) -> None:
        """黄金样本：合格文档集通过格式门控。"""
        pkg_dir = GOLDEN / "valid_docset"
        if not pkg_dir.exists():
            pytest.skip("黄金样本不存在")

        config = PipelineConfig(
            stages=[
                StageConfig(
                    id="format",
                    short_circuit_policy="fail_fast",
                    evaluators=[
                        EvaluatorConfig("format.response_format", {"allowed_formats": ["md"]}),
                        EvaluatorConfig("format.document_count", {"min": 1, "max": 10}),
                        EvaluatorConfig("format.structure_compliance"),
                    ],
                ),
            ]
        )
        engine = PipelineEngine(config, registry)
        result = engine.evaluate_sample(pkg_dir, {"sample_id": "golden_valid"})

        assert result.stage_results["format"].gate_passed is True
        assert result.s_format == 1.0

    def test_golden_format_invalid(self) -> None:
        """黄金样本：格式异常文档集被门控拦截。"""
        pkg_dir = GOLDEN / "format_invalid"
        if not pkg_dir.exists():
            pytest.skip("黄金样本不存在")

        config = PipelineConfig(
            stages=[
                StageConfig(
                    id="format",
                    short_circuit_policy="fail_fast",
                    evaluators=[
                        EvaluatorConfig("format.structure_compliance"),
                    ],
                ),
            ]
        )
        engine = PipelineEngine(config, registry)
        result = engine.evaluate_sample(pkg_dir, {"sample_id": "golden_fmt_invalid"})

        assert result.stage_results["format"].gate_passed is False

    def test_cache_hit(self, tmp_path: Path) -> None:
        """相同输入重复评估命中缓存。"""
        output = tmp_path / "output"
        output.mkdir()
        (output / "doc.md").write_text("# Title\n\nContent.")

        config = PipelineConfig(
            stages=[
                StageConfig(
                    id="format",
                    short_circuit_policy="fail_fast",
                    evaluators=[
                        EvaluatorConfig("format.response_format", {"allowed_formats": ["md"]}),
                    ],
                ),
            ]
        )
        engine = PipelineEngine(config, registry)

        r1 = engine.evaluate_sample(tmp_path, {"sample_id": "cache_test"})
        r2 = engine.evaluate_sample(tmp_path, {"sample_id": "cache_test"})
        # 应返回缓存的同一结果
        assert r1.sample_id == r2.sample_id

    def test_batch_evaluation(self, tmp_path: Path) -> None:
        """批量评估返回 MetricsReport。"""
        for i in range(3):
            d = tmp_path / f"pkg_{i}"
            out = d / "output"
            out.mkdir(parents=True)
            (out / "doc.md").write_text(f"# Doc {i}\n\n## Section\n")

        packages = [tmp_path / f"pkg_{i}" for i in range(3)]

        config = PipelineConfig(
            stages=[
                StageConfig(
                    id="format",
                    short_circuit_policy="fail_fast",
                    evaluators=[
                        EvaluatorConfig("format.response_format", {"allowed_formats": ["md"]}),
                        EvaluatorConfig("format.document_count", {"min": 1, "max": 10}),
                    ],
                ),
            ]
        )
        engine = PipelineEngine(config, registry)
        report = engine.evaluate_batch(packages, run_id="run_batch")

        assert report.total_samples == 3
        assert report.dr == 1.0
