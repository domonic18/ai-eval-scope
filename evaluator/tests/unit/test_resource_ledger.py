"""ResourceLedger / EvidenceLedger 单测。"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from agent_eval.agent.executor.ledger import EvidenceLedger, ResourceLedger
from agent_eval.execution.models import InteractionPolicy


def _digest(payload: dict) -> dict:
    return payload["error"]


class TestResourceLedgerAuthorize:
    """额度仲裁：消耗即记账、拒绝带指引、backoff 是节奏信号。"""

    def test_dispatch_then_exhaust(self) -> None:
        ledger = ResourceLedger(InteractionPolicy(dispatch=1))
        assert ledger.authorize("dispatch") is None
        assert ledger.counters["dispatch"] == 1
        assert ledger.counters["sut_call"] == 1

        payload = ledger.authorize("dispatch")
        assert payload is not None
        err = _digest(payload)
        assert payload["status"] == "failed"
        assert err["type"] == "BudgetExhausted"
        assert err["budget"] == "dispatch"
        assert err["used"] == 1
        assert err["limit"] == 1
        assert "write_package" in err["guidance"]
        assert isinstance(payload["ledger_digest"], list)
        # 拒绝不重复消耗
        assert ledger.counters["dispatch"] == 1
        assert len(ledger.refusals) == 1

    def test_total_exhaustion_refuses_nudge(self) -> None:
        ledger = ResourceLedger(InteractionPolicy(sut_calls_total=2, dispatch=1, nudges=1))
        assert ledger.authorize("dispatch") is None
        assert ledger.authorize("nudge") is None
        payload = ledger.authorize("nudge")
        assert payload is not None
        # 合计面先于分类面拒绝
        assert _digest(payload)["budget"] == "sut_calls_total"

    def test_nudge_backoff_refusal_does_not_consume(self) -> None:
        ledger = ResourceLedger(InteractionPolicy(nudge_backoff_s=30))
        assert ledger.authorize("nudge") is None
        ledger.last_nudge_at = time.monotonic()
        payload = ledger.authorize("nudge")
        assert payload is not None
        err = _digest(payload)
        assert err["budget"] == "nudge_backoff"
        assert "等待" in err["message"]
        # 节奏窗口不烧额度
        assert ledger.counters["nudge"] == 1
        assert ledger.counters["sut_call"] == 1

    def test_nudge_backoff_elapsed_allows(self) -> None:
        ledger = ResourceLedger(InteractionPolicy(nudge_backoff_s=30))
        assert ledger.authorize("nudge") is None
        ledger.last_nudge_at = time.monotonic() - 31
        assert ledger.authorize("nudge") is None
        assert ledger.counters["nudge"] == 2

    def test_state_poll_and_download_gates(self) -> None:
        ledger = ResourceLedger(InteractionPolicy(state_polls=2, downloads=1))
        assert ledger.authorize("state_poll") is None
        assert ledger.authorize("state_poll") is None
        payload = ledger.authorize("state_poll")
        assert _digest(payload)["budget"] == "state_polls"

        # download 额度独立（1 次仍可用）
        assert ledger.authorize("download") is None
        assert _digest(ledger.authorize("download"))["budget"] == "downloads"

    def test_download_pass_then_exhaust(self) -> None:
        ledger = ResourceLedger(InteractionPolicy(downloads=1))
        assert ledger.authorize("download") is None
        payload = ledger.authorize("download")
        assert _digest(payload)["budget"] == "downloads"
        assert _digest(payload)["guidance"].startswith("下载额度已用尽")

    def test_wall_clock_refusal_blocks_all_actions(self) -> None:
        ledger = ResourceLedger(InteractionPolicy(wall_clock_deadline_s=100))
        ledger._started_monotonic = time.monotonic() - 200
        for action in ("dispatch", "nudge", "state_poll", "download"):
            payload = ledger.authorize(action)
            assert payload is not None, action
            assert _digest(payload)["budget"] == "wall_clock"
            assert "write_package" in _digest(payload)["guidance"]

    def test_unknown_action_raises(self) -> None:
        ledger = ResourceLedger(InteractionPolicy())
        with pytest.raises(ValueError, match="未知预算动作"):
            ledger.authorize("teleport")

    def test_sut_call_action_for_total_only_budget(self) -> None:
        """generic_http 直接调用面：只受合计面约束，无 dispatch 单发限制。"""
        ledger = ResourceLedger(InteractionPolicy(sut_calls_total=3, dispatch=1))
        for _ in range(3):
            assert ledger.authorize("sut_call") is None
        payload = ledger.authorize("sut_call")
        assert _digest(payload)["budget"] == "sut_calls_total"


class TestResourceLedgerViews:
    """视图：remaining 与 budget_digest。"""

    def test_remaining_format(self) -> None:
        ledger = ResourceLedger(InteractionPolicy(state_polls=3))
        ledger.authorize("state_poll")
        ledger.authorize("state_poll")
        assert ledger.remaining("state_poll") == "1/3"

    def test_budget_digest_shape(self) -> None:
        ledger = ResourceLedger(InteractionPolicy())
        digest = {item["budget"]: item for item in ledger.budget_digest()}
        assert digest["sut_calls_total"]["used"] == 0
        assert digest["sut_calls_total"]["limit"] == 8
        assert digest["nudges"]["limit"] == 2
        assert "used_s" in digest["wall_clock"]
        assert digest["wall_clock"]["limit"] == 1500.0


class TestResourceLedgerEvidence:
    """证据联动：record 落事件流、拒绝自动记 gate_refusal。"""

    def test_record_logs_evidence_event(self) -> None:
        evidence = EvidenceLedger()
        ledger = ResourceLedger(InteractionPolicy(), evidence=evidence)
        ledger.authorize("dispatch")
        ledger.record("dispatch", "ok", duration_s=1.2346, summary="课件已生成")
        event = evidence.events[-1]
        assert event["kind"] == "sut_call"
        assert event["action"] == "dispatch"
        assert event["outcome"] == "ok"
        assert event["duration_s"] == 1.235
        assert event["summary"] == "课件已生成"
        assert "ts" in event

    def test_record_truncates_long_summary(self) -> None:
        evidence = EvidenceLedger()
        ledger = ResourceLedger(InteractionPolicy(), evidence=evidence)
        ledger.authorize("state_poll")
        ledger.record("state_poll", "ok", summary="x" * 500)
        assert len(evidence.events[-1]["summary"]) == 200

    def test_record_without_evidence_is_noop(self) -> None:
        ledger = ResourceLedger(InteractionPolicy())
        ledger.authorize("dispatch")
        ledger.record("dispatch", "ok")  # 不抛异常即通过

    def test_gate_refusal_logged_to_evidence(self) -> None:
        evidence = EvidenceLedger()
        ledger = ResourceLedger(InteractionPolicy(dispatch=1), evidence=evidence)
        ledger.authorize("dispatch")
        ledger.authorize("dispatch")
        refusal_events = [e for e in evidence.events if e["kind"] == "gate_refusal"]
        assert len(refusal_events) == 1
        assert refusal_events[0]["action"] == "dispatch"
        assert refusal_events[0]["budget"] == "dispatch"

    def test_download_maps_to_artifact_kind(self) -> None:
        evidence = EvidenceLedger()
        ledger = ResourceLedger(InteractionPolicy(), evidence=evidence)
        ledger.authorize("download")
        ledger.record("download", "ok", summary=["a.html"])
        assert evidence.events[-1]["kind"] == "artifact"


class TestRefusalEscalation:
    """连拒升级：同 action 连拒 ≥3 次点名收尾路径，打断即重计。"""

    def test_refusal_streak_counts_tail_and_resets_on_other_action(self) -> None:
        ledger = ResourceLedger(InteractionPolicy())
        for _ in range(3):
            ledger.register_refusal("nudge", {"budget": "nudge_rationale"})
        assert ledger._refusal_streak("nudge") == 3
        ledger.register_refusal("state_poll", {"budget": "state_polls"})
        assert ledger._refusal_streak("nudge") == 0
        assert ledger._refusal_streak("state_poll") == 1

    def test_register_refusal_escalates_from_third_consecutive(self) -> None:
        ledger = ResourceLedger(InteractionPolicy())
        error = {"budget": "nudge_rationale"}
        assert ledger.register_refusal("nudge", error) is None
        assert "escalation" not in error
        ledger.register_refusal("nudge", {"budget": "nudge_rationale"})
        escalation = ledger.register_refusal("nudge", {"budget": "nudge_rationale"})
        assert escalation is not None
        assert "连续拒绝 3 次" in escalation
        assert "write_package" in escalation

    def test_refuse_payload_and_evidence_carry_escalation(self) -> None:
        evidence = EvidenceLedger()
        ledger = ResourceLedger(InteractionPolicy(state_polls=1), evidence=evidence)
        assert ledger.authorize("state_poll") is None  # 放行烧尽额度
        payload = None
        for _ in range(3):
            payload = ledger.authorize("state_poll")  # 连续 3 次拒绝
        assert payload is not None
        assert "escalation" in _digest(payload)
        refusal_events = [e for e in evidence.events if e["kind"] == "gate_refusal"]
        assert "escalation" in refusal_events[-1]


class TestEvidenceLedger:
    """证据台账落盘。"""

    def test_log_event_shape(self) -> None:
        ledger = EvidenceLedger()
        event = ledger.log("sut_call", action="dispatch", outcome="ok")
        assert event["kind"] == "sut_call"
        assert event["action"] == "dispatch"
        assert ledger.events == [event]

    def test_dump_writes_jsonl(self, tmp_path: Path) -> None:
        ledger = EvidenceLedger()
        ledger.log("sut_call", action="dispatch", outcome="ok", summary="生成《春》课件")
        ledger.log("gate_refusal", action="nudge", budget="nudge_backoff")
        path = ledger.dump(tmp_path / "packages" / "t1")
        assert path.name == "ledger.jsonl"
        lines = path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 2
        first = json.loads(lines[0])
        assert first["kind"] == "sut_call"
        # ensure_ascii=False——中文原文可读
        assert json.loads(lines[0])["summary"] == "生成《春》课件"
        assert json.loads(lines[1])["budget"] == "nudge_backoff"

    def test_dump_empty_ledger_writes_empty_file(self, tmp_path: Path) -> None:
        path = EvidenceLedger().dump(tmp_path)
        assert path.exists()
        assert path.read_text(encoding="utf-8") == ""
