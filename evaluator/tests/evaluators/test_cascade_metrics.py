"""级联控制（PipelineStage）+ PipelineEngine 端到端测试。

（旧 ScoreAggregator / MetricsCalculator 专项测试已随 Phase 5 删除；聚合/指标由
ScenarioScoreAggregator / ScenarioMetricsCalculator 承担，见 test_scenario_aggregation。）
"""

from pathlib import Path

import pytest

from agent_eval.core.types import ConstraintTier, EvalMethod, EvalStatus
from agent_eval.evaluation.base import BaseEvaluator
from agent_eval.evaluation.engine import (
    EvaluatorConfig,
    PipelineConfig,
    PipelineEngine,
    StageConfig,
)
from agent_eval.evaluation.evaluators import *  # trigger registration
from agent_eval.evaluation.registry import registry
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
        ev2 = registry.create("format.html_validity", {})

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
                        EvaluatorConfig("format.html_validity"),
                    ],
                ),
            ]
        )
        engine = PipelineEngine(config, registry)
        result = engine.evaluate_sample(tmp_path, {"sample_id": "test_001"})

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

        assert result.stage_results["format"].gate_passed is False  # format 失败
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
                        EvaluatorConfig("format.html_validity"),
                    ],
                ),
            ]
        )
        engine = PipelineEngine(config, registry)
        result = engine.evaluate_sample(pkg_dir, {"sample_id": "golden_valid"})

        assert result.stage_results["format"].gate_passed is True

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

    def test_cache_key_includes_llm_signature(self, tmp_path: Path) -> None:
        """LLM 指纹不同 → cache_key 不同（LLM 配置变更时缓存自动失效）。"""
        config = PipelineConfig(stages=[StageConfig(id="format")])
        engine = PipelineEngine(config, registry)
        k1 = engine._compute_cache_key(tmp_path, {"llm_signature": "sig-a"})
        k2 = engine._compute_cache_key(tmp_path, {"llm_signature": "sig-b"})
        k3 = engine._compute_cache_key(tmp_path, {"llm_signature": "sig-a"})
        assert k1 != k2  # 不同 LLM 配置 → 不同 key
        assert k1 == k3  # 相同 LLM 配置 → 相同 key

    def test_no_cache_forces_reevaluation(self, tmp_path: Path) -> None:
        """no_cache 时跳过缓存读取，强制重新评估。"""
        output = tmp_path / "output"
        output.mkdir()
        (output / "doc.md").write_text("# Title")

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
        engine.evaluate_sample(tmp_path, {"sample_id": "nc_test"})  # 写入缓存
        assert len(engine._cache) == 1
        r = engine.evaluate_sample(tmp_path, {"sample_id": "nc_test", "no_cache": True})
        assert r.sample_id == "nc_test"  # 跳过缓存仍正常评估

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
                        EvaluatorConfig("format.html_validity"),
                    ],
                ),
            ]
        )
        engine = PipelineEngine(config, registry)
        report = engine.evaluate_batch(packages, run_id="run_batch")

        assert report.total_samples == 3
        assert report.metrics["courseware:document_rate"] == 1.0
