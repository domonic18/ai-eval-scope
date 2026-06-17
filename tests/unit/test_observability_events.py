"""observability 事件映射单测（docs/arch/09 §8.2）。"""

from __future__ import annotations

from agent_eval.core.types import ConstraintTier, EvalStatus
from agent_eval.evaluation.models import (
    ConstraintResult,
    MetricsReport,
    SampleResult,
    StageResult,
)
from agent_eval.observability.events import (
    build_constraint_event,
    build_run_event,
    build_sample_event,
)


def _constraint(
    constraint_id="format.title", *, status=EvalStatus.PASS, tier=ConstraintTier.HARD_GATE
):
    return ConstraintResult(
        constraint_id=constraint_id,
        name="has title",
        tier=tier,
        status=status,
        score=1.0,
        reason="ok",
        judge_provider="deepseek_judge",
        judge_model="deepseek-chat",
    )


def _sample(sample_id="sample_001"):
    s = SampleResult(sample_id=sample_id, status=EvalStatus.PASS, s_format=1.0, reward=0.8)
    s.stage_results = {
        "format": StageResult(
            stage_id="format", status=EvalStatus.PASS, constraint_results=[_constraint()]
        )
    }
    return s


def test_run_event_mapping_fields():
    report = MetricsReport(
        run_id="run_1",
        total_samples=2,
        dr=0.9,
        cpr=0.7,
        avg_reward=0.6,
        cond_r=0.65,
        avg_time_ms=1200,
    )
    ev = build_run_event(report, langfuse_host="https://lf")
    assert ev["type"] == "run"
    assert ev["event_id"]
    d = ev["data"]
    assert d["external_run_id"] == "run_1"
    assert d["mode"] == "eval_only"
    assert d["metrics"] == {
        "DR": 0.9,
        "CPR": 0.7,
        "avg_reward": 0.6,
        "condR": 0.65,
        "avg_time_ms": 1200,
    }
    assert d["total_samples"] == 2
    assert d["langfuse_host"] == "https://lf"


def test_sample_event_mapping_fields():
    ev = build_sample_event(_sample(), external_run_id="run_1")
    assert ev["type"] == "sample"
    d = ev["data"]
    assert d["external_run_id"] == "run_1"
    assert d["external_sample_id"] == "sample_001"
    assert d["s_format"] == 1.0
    assert d["reward"] == 0.8


def test_constraint_event_mapping_and_passed_derivation():
    ev = build_constraint_event(
        _constraint(), external_run_id="run_1", external_sample_id="sample_001"
    )
    d = ev["data"]
    assert d["constraint_id"] == "format.title"
    assert d["tier"] == "hard_gate"
    assert d["status"] == "pass"
    # passed 由 status 派生（schema 字段）
    assert d["passed"] is True
    assert d["judge_provider"] == "deepseek_judge"
    assert d["judge_record_object_key"] is None  # 未上传制品前为 None

    # fail → passed False
    ev_fail = build_constraint_event(
        _constraint(status=EvalStatus.FAIL), external_run_id="run_1", external_sample_id="s"
    )
    assert ev_fail["data"]["passed"] is False
    assert ev_fail["data"]["status"] == "fail"
