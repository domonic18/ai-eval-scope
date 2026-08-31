"""observability ResultSink 单测（事件拼装面，不联网）。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from agent_eval.core.types import EvalStatus
from agent_eval.evaluation.models import MetricsReport, SampleResult, StageResult
from agent_eval.observability.config import load_config
from agent_eval.observability.sink import ResultSink, SinkReport
from agent_eval.orchestrator.orchestrator import EvalResult


def _sample(sample_id: str = "sample_001") -> SampleResult:
    s = SampleResult(sample_id=sample_id, status=EvalStatus.PASS, reward=0.8)
    s.stage_results = {
        "format": StageResult(
            stage_id="format",
            status=EvalStatus.PASS,
            constraint_results=[],
        )
    }
    return s


def _result() -> EvalResult:
    """模拟 eval-only / 调试台路径的产物：无 W6 SUT 身份回填、无 rule_set/scenario_config。"""
    report = MetricsReport(
        run_id="run_1",
        total_samples=1,
        metrics={"courseware:reward": 0.6},
        avg_time_ms=1,
    )
    return EvalResult(report=report, samples=[_sample()])


def _sink() -> ResultSink:
    # client/queue 注入 MagicMock：_build_events 只拼事件，不发网络请求、不落盘
    return ResultSink(load_config(), client=MagicMock(), queue=MagicMock())


def test_build_events_eval_only_without_sut_backfill(tmp_path: Path) -> None:
    """回归：EvalResult 必须声明 sut_name/sut_version 字段。

    曾因字段缺失，executor 在 flush 时报 'EvalResult' object has no attribute
    'sut_version'，结果回传静默失败（sent=0，平台页无 run 数据）。
    """
    sink = _sink()
    events = sink._build_events(_result(), run_workspace=tmp_path, report=SinkReport(enabled=True))
    assert events[0]["type"] == "run"
    # 无人回填 → 空串被 sink 归一为 None（run event 不带 SUT 身份）
    assert events[0]["data"]["sut_version"] is None
    # 样本事件仍正常拼装
    assert [e["type"] for e in events] == ["run", "sample"]
