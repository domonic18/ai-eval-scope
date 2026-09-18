"""失败语义分层（AgentCompass P0-1）测试：执行失败 ≠ 评得低分。

验证三件事：
1. manifest.status=failed 的执行包在 evaluate_sample 短路为 RUN_ERROR——不进 stage
   评估（半张卷子的分数只会误导）、reward 0.0、照常写缓存；
2. partial / success 包不受短路影响，照常逐阶段评估；
3. compute_metrics 暴露 run_error_count / error_rate，且 RUN_ERROR 样本被剔除出
   指标数组与 total 分母（ScenarioMetricsCalculator 侧）。
"""

from __future__ import annotations

from pathlib import Path

import agent_eval.evaluation.evaluators  # noqa: F401  触发评估器注册
from agent_eval.core.types import EvalStatus, PackageStatus
from agent_eval.evaluation.engine import (
    EvaluatorConfig,
    PipelineConfig,
    PipelineEngine,
    StageConfig,
)
from agent_eval.evaluation.models import SampleResult
from agent_eval.evaluation.registry import registry
from agent_eval.storage.package import ExecutionPackage, PackageManifest


def _make_result(sid: str, status: EvalStatus, *, reward: float) -> SampleResult:
    r = SampleResult(sample_id=sid, status=status)
    r.stage_metrics = {"reward": reward}
    r.reward = reward
    return r


def _engine() -> PipelineEngine:
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
    return PipelineEngine(config, registry)


def _package(status: PackageStatus, tmp_path: Path) -> ExecutionPackage:
    return ExecutionPackage(
        manifest=PackageManifest(
            package_id=f"pkg-{status.value}",
            created_at="2026-09-12T00:00:00+00:00",
            task_id=f"task-{status.value}",
            status=status,
        ),
        output_dir=tmp_path,
    )


def _valid_doc_dir(tmp_path: Path) -> Path:
    (tmp_path / "output").mkdir(exist_ok=True)
    (tmp_path / "output" / "doc.md").write_text("# Title\n\nContent.", encoding="utf-8")
    return tmp_path


# ── C2：执行失败包短路 ──────────────────────────────────────────────────────────


def test_failed_package_short_circuits_to_run_error(tmp_path: Path) -> None:
    engine = _engine()
    result = engine.evaluate_sample(_package(PackageStatus.FAILED, tmp_path), {"sample_id": "t1"})

    assert result.status == EvalStatus.RUN_ERROR
    assert result.stage_results == {}  # 短路：未进任何 stage 评估
    assert result.stage_metrics == {}
    assert result.reward == 0.0
    assert len(engine._cache) == 1  # 照常写缓存——同包重评估结果一致


def test_failed_package_reevaluation_hits_cache(tmp_path: Path) -> None:
    engine = _engine()
    pkg = _package(PackageStatus.FAILED, tmp_path)
    r1 = engine.evaluate_sample(pkg, {"sample_id": "t1"})
    r2 = engine.evaluate_sample(pkg, {"sample_id": "t1"})
    assert r1 is r2
    assert r2.status == EvalStatus.RUN_ERROR


def test_partial_package_still_evaluated(tmp_path: Path) -> None:
    """partial（部分产物）仍有评估价值——不短路，照常逐阶段评估。"""
    engine = _engine()
    result = engine.evaluate_sample(
        _package(PackageStatus.PARTIAL, _valid_doc_dir(tmp_path)), {"sample_id": "t2"}
    )

    assert result.status == EvalStatus.PASS
    assert "format" in result.stage_results
    assert result.reward > 0.0


def test_success_package_unaffected(tmp_path: Path) -> None:
    engine = _engine()
    result = engine.evaluate_sample(
        _package(PackageStatus.SUCCESS, _valid_doc_dir(tmp_path)), {"sample_id": "t3"}
    )

    assert result.status == EvalStatus.PASS
    assert "format" in result.stage_results


def test_non_package_sample_unaffected(tmp_path: Path) -> None:
    """Path 等非 ExecutionPackage 样本无 manifest 字段——防御读取走默认分支。"""
    engine = _engine()
    result = engine.evaluate_sample(_valid_doc_dir(tmp_path), {"sample_id": "t4"})

    assert result.status == EvalStatus.PASS
    assert "format" in result.stage_results


# ── C3：run_error_count / error_rate 与分母剔除 ────────────────────────────────


def test_compute_metrics_exposes_run_error_count_and_rate() -> None:
    engine = _engine()
    passing = _make_result("ok", EvalStatus.PASS, reward=0.8)
    failing = _make_result("bad", EvalStatus.FAIL, reward=0.2)
    run_error = _make_result("dead", EvalStatus.RUN_ERROR, reward=0.0)

    report = engine.compute_metrics([passing, failing, run_error], run_id="r")

    assert report.metrics["run_error_count"] == 1.0
    assert report.metrics["error_rate"] == 1.0 / 3
    assert report.total_samples == 3


def test_metrics_expression_excludes_run_error_from_denominator() -> None:
    """RUN_ERROR 样本不进指标数组：mean(reward) 只均 2 个可评估样本。"""
    engine = _engine()
    passing = _make_result("ok", EvalStatus.PASS, reward=0.8)
    failing = _make_result("bad", EvalStatus.FAIL, reward=0.2)
    run_error = _make_result("dead", EvalStatus.RUN_ERROR, reward=0.0)

    report = engine.compute_metrics([passing, failing, run_error], run_id="r")

    # 无 run_error 污染：(0.8 + 0.2) / 2 = 0.5（污染则为 1/3 ≈ 0.333）
    assert report.metrics["courseware:reward"] == 0.5


def test_metrics_all_run_error_returns_empty_definitions() -> None:
    """全部执行失败：指标定义表达式无值可算（防 total=0 除零），仅剩附加字段。"""
    engine = _engine()
    run_error = _make_result("dead", EvalStatus.RUN_ERROR, reward=0.0)

    report = engine.compute_metrics([run_error], run_id="r")

    assert report.metrics["run_error_count"] == 1.0
    assert report.metrics["error_rate"] == 1.0
    # policy 声明的表达式指标全部缺席（compute 返回空）
    assert "courseware:reward" not in report.metrics


def test_run_error_result_carries_diag_summary_and_duration(tmp_path: Path) -> None:
    """合同五（arch/16 §4.6）：run_error 样本带 trace 诊断（error_summary + 真实
    执行时长）——Web 端「无结果」可解释，不再 duration=0 无说明（run
    20260916_074046 media_001：真实 151s 丢失）。"""
    pkg = _package(PackageStatus.FAILED, tmp_path)
    pkg.trace = {
        "error": "Agent 会话异常中断: Connection error.",
        "response": {"duration_ms": 151000.0},
    }
    engine = _engine()
    result = engine.evaluate_sample(pkg, {"sample_id": "t1"})
    assert result.status == EvalStatus.RUN_ERROR
    assert result.error_summary == "Agent 会话异常中断: Connection error."
    assert result.total_duration_ms == 151000.0
