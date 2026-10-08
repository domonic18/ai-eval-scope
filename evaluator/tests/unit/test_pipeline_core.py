"""pipeline_core 单测。

覆盖 CLI 壳测不到的纯函数面：异常→outcome 映射逐行、progress 事件序、
钩子时点（credential_filler 先于 RESOLVE_INFO）、协作取消（130）、
门禁失败携 payload。渲染本身由 golden 快照锁定（test_cli_pipeline_golden）。
"""

from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_eval.cli.pipeline_core import PipelineParams, PipelineStage, pipeline_core
from agent_eval.core.exceptions import AgentEvalError

RUN_ID = "20260101_000000"


def _inputs(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        resolved_pkg=None,
        task_set_path=tmp_path / "default.yaml",
        task_set_model=SimpleNamespace(tasks=[{}, {}]),
        config_path=tmp_path / "sut",
        sut=SimpleNamespace(name="cw-agent", channel="agent_protocol", base_url="http://x"),
    )


def _result() -> SimpleNamespace:
    return SimpleNamespace(
        run_id=RUN_ID,
        samples=[],
        report=SimpleNamespace(metrics={"m:reward": 0.9}, total_samples=2),
        gate={"mode": "off", "enabled": False, "passed": True},
    )


def _gate_fail_result() -> SimpleNamespace:
    r = _result()
    r.gate = {"mode": "strict", "enabled": True, "passed": False, "failures": ["m:reward 低"]}
    return r


def _packages() -> list[SimpleNamespace]:
    return [
        SimpleNamespace(
            manifest=SimpleNamespace(task_id="t1", status="success", package_id="t1"),
            output_dir="t1",
        )
    ]


class _Harness:
    """五阶段桩 + run_id + 上报隔离（enabled=False 静默路径）。"""

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import agent_eval.cli._common as common
        import agent_eval.cli._stages as stages
        import agent_eval.storage.package as storage_pkg

        self.tmp_path = tmp_path
        self.calls: dict[str, dict] = {}
        self.events: list[PipelineStage] = []
        self.journal: list[str] = []  # 跨钩子时序账本（filler vs 事件）
        monkeypatch.setenv("AGENT_EVAL_UPLOAD", "0")
        monkeypatch.setattr(stages, "resolve_run_inputs", lambda *a, **k: _inputs(tmp_path))
        monkeypatch.setattr(
            stages, "resolve_eval_inputs", lambda *a, **k: str(tmp_path / "rules.yaml")
        )
        monkeypatch.setattr(stages, "build_judge_context", lambda *a, **k: object())
        monkeypatch.setattr(
            stages,
            "execute_stage",
            lambda *a, **k: (self.calls.setdefault("execute", dict(k)), _packages())[1],
        )
        monkeypatch.setattr(stages, "evaluate_stage", lambda *a, **k: _result())
        monkeypatch.setattr(
            stages,
            "finalize_eval",
            lambda *a, **k: self.calls.setdefault("finalize", dict(k)),
        )
        monkeypatch.setattr(common, "observability_enabled", lambda *a, **k: False)
        monkeypatch.setattr(common, "observability_flush", lambda *a, **k: {"enabled": False})
        monkeypatch.setattr(storage_pkg, "generate_run_id", lambda: RUN_ID)

    def params(self, **kw) -> PipelineParams:
        return PipelineParams(output_dir=str(self.tmp_path / "ws"), **kw)

    def progress(self, stage: PipelineStage, payload: dict) -> None:
        self.events.append(stage)
        self.journal.append(stage.value)

    def fail(self, stage: str, monkeypatch: pytest.MonkeyPatch, exc: Exception) -> None:
        import agent_eval.cli._stages as stages

        monkeypatch.setattr(stages, stage, _raiser(exc))


def _raiser(exc: Exception):
    def _raise(*a, **k):
        raise exc

    return _raise


def test_event_sequence_and_outcome(tmp_path, monkeypatch) -> None:
    h = _Harness(tmp_path, monkeypatch)
    outcome = pipeline_core(h.params(), progress=h.progress)
    assert [s for s in h.events] == [
        PipelineStage.RESOLVE_INFO,
        PipelineStage.EXECUTE,
        PipelineStage.EXECUTE_DONE,
        PipelineStage.EVALUATE,
        PipelineStage.FINALIZE,
        PipelineStage.SUMMARY,
        PipelineStage.UPLOAD_START,
        PipelineStage.UPLOAD,
        PipelineStage.DONE,
    ]
    assert outcome.stage == "done" and outcome.exit_code == 0 and outcome.ok
    assert outcome.run_id == RUN_ID
    assert outcome.run_dir.endswith(f"runs/{RUN_ID}")
    assert outcome.metrics == {"m:reward": 0.9}
    assert outcome.total_samples == 2
    # payload 指标真相在 result.report
    assert outcome.payload["metrics"] == {"m:reward": 0.9}
    assert outcome.payload["total_samples"] == 2
    assert outcome.upload_receipt == {"enabled": False}
    assert outcome.gate == {"mode": "off", "enabled": False, "passed": True}


def test_progress_none_silent_success(tmp_path, monkeypatch) -> None:
    h = _Harness(tmp_path, monkeypatch)
    outcome = pipeline_core(h.params())  # progress 缺省 None 不炸
    assert outcome.ok


def test_gate_config_error_fails_fast(tmp_path, monkeypatch) -> None:
    h = _Harness(tmp_path, monkeypatch)
    outcome = pipeline_core(h.params(gate="bogus"), progress=h.progress)
    assert (outcome.stage, outcome.exit_code) == ("gate_config", 1)
    assert outcome.error_type == "GateConfigError"
    assert "不可解析" in outcome.error
    assert h.events == [PipelineStage.ABORT]  # 未进 resolve/execute


def test_resolve_failure(tmp_path, monkeypatch) -> None:
    h = _Harness(tmp_path, monkeypatch)
    h.fail("resolve_run_inputs", monkeypatch, AgentEvalError("包不存在"))
    outcome = pipeline_core(h.params(), progress=h.progress)
    assert (outcome.stage, outcome.exit_code) == ("resolve", 1)
    assert outcome.run_id == ""  # run_id 尚未生成
    assert h.events == [PipelineStage.ABORT]


def test_credential_filler_runs_before_resolve_info(tmp_path, monkeypatch) -> None:
    h = _Harness(tmp_path, monkeypatch)
    seen: list = []

    def filler(sut) -> None:
        seen.append(sut)
        h.journal.append("filler")

    outcome = pipeline_core(h.params(), progress=h.progress, credential_filler=filler)
    assert outcome.ok
    assert seen and seen[0].name == "cw-agent"
    # 时点：resolve 后、RESOLVE_INFO 前（进度视图启动前完成补录）
    assert h.journal[0] == "filler" and h.journal[1] == "resolve_info"


def test_credential_filler_error_maps_credentials(tmp_path, monkeypatch) -> None:
    h = _Harness(tmp_path, monkeypatch)

    def filler(sut) -> None:
        h.journal.append("filler")
        raise AgentEvalError("凭证缺失: api_key")

    outcome = pipeline_core(h.params(), progress=h.progress, credential_filler=filler)
    assert (outcome.stage, outcome.exit_code) == ("credentials", 1)
    assert "api_key" in outcome.error
    # 失败发生在任何输出事件之前（ABORT 幂等关视图是唯一后续事件）
    assert h.journal == ["filler", "abort"]


def test_execute_failure_keeps_run_id(tmp_path, monkeypatch) -> None:
    h = _Harness(tmp_path, monkeypatch)
    h.fail("execute_stage", monkeypatch, AgentEvalError("通道不可用"))
    outcome = pipeline_core(h.params(), progress=h.progress)
    assert (outcome.stage, outcome.exit_code) == ("execute", 1)
    assert outcome.run_id == RUN_ID
    assert outcome.run_dir.endswith(f"runs/{RUN_ID}")
    assert PipelineStage.EXECUTE in h.events and PipelineStage.EVALUATE not in h.events


def test_evaluate_failure_maps_generic_exception(tmp_path, monkeypatch) -> None:
    h = _Harness(tmp_path, monkeypatch)
    h.fail("evaluate_stage", monkeypatch, RuntimeError("judge 崩溃"))
    outcome = pipeline_core(h.params(), progress=h.progress)
    # 兜底映射：非 AgentEvalError 同样落 evaluate 段 exit 1（与 CLI 现行一致）
    assert (outcome.stage, outcome.exit_code) == ("evaluate", 1)
    assert outcome.error_type == "RuntimeError"
    assert "judge 崩溃" in outcome.error


def test_cancel_preset_returns_130_without_evaluation(tmp_path, monkeypatch) -> None:
    h = _Harness(tmp_path, monkeypatch)
    cancel = threading.Event()
    cancel.set()
    outcome = pipeline_core(h.params(), progress=h.progress, cancel_event=cancel)
    assert (outcome.stage, outcome.exit_code) == ("cancelled", 130)
    assert outcome.cancelled is True and not outcome.ok
    assert outcome.run_id == RUN_ID  # 产物与清单已落盘，可溯源
    # EXECUTE_DONE（部分计数）已发；不进评估/上报
    assert PipelineStage.EXECUTE_DONE in h.events
    assert PipelineStage.EVALUATE not in h.events
    assert PipelineStage.DONE not in h.events


def test_cancel_event_passed_to_execute_stage(tmp_path, monkeypatch) -> None:
    h = _Harness(tmp_path, monkeypatch)
    cancel = threading.Event()
    pipeline_core(h.params(), cancel_event=cancel)
    assert h.calls["execute"]["cancel_event"] is cancel


def test_gate_failure_exit3_carries_payload(tmp_path, monkeypatch) -> None:
    import agent_eval.cli._stages as stages

    h = _Harness(tmp_path, monkeypatch)
    monkeypatch.setattr(stages, "evaluate_stage", lambda *a, **k: _gate_fail_result())
    outcome = pipeline_core(h.params(), progress=h.progress)
    assert (outcome.stage, outcome.exit_code) == ("gate", 3)
    # 门禁判定在上报之后：DONE 已发、payload/metrics/result 随行（JSON 先行语义）
    assert h.events[-1] == PipelineStage.DONE
    assert outcome.payload is not None and outcome.payload["metrics"] == {"m:reward": 0.9}
    assert outcome.metrics == {"m:reward": 0.9}
    assert outcome.gate["passed"] is False
    assert outcome.result is not None


def test_params_passthrough_to_evaluate_stage(tmp_path, monkeypatch) -> None:
    import agent_eval.cli._stages as stages

    h = _Harness(tmp_path, monkeypatch)
    calls: dict = {}
    monkeypatch.setattr(
        stages,
        "evaluate_stage",
        lambda *a, **k: (calls.update(k), _result())[1],
    )
    pipeline_core(
        h.params(
            gate="strict", no_cache=True, report_formats=["junit"], project="p1", concurrency=4
        )
    )
    assert calls["gate"] == "strict"
    assert calls["no_cache"] is True
    assert calls["report_formats"] == ["junit"]  # 已解析形态透传（壳解析留 CLI 语义）
    assert calls["project"] == "p1"
    assert calls["max_concurrency"] == 4  # 样本级并发评估（CLI --concurrency）
