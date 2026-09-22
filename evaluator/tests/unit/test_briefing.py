"""决策简报聚合器单测——观察时间线/候选提取/聚合字段。"""

from __future__ import annotations

import time

from agent_eval.agent.executor.briefing import (
    SutStateTracker,
    build_briefing,
    extract_artifact_candidates,
    instruction_digest,
)
from agent_eval.agent.executor.ledger import EvidenceLedger, ResourceLedger
from agent_eval.execution.models import InteractionPolicy


def _policy(**overrides: int) -> InteractionPolicy:
    return InteractionPolicy(**{"sut_calls_total": 8, "wall_clock_deadline_s": 1500, **overrides})


def _ledger() -> ResourceLedger:
    return ResourceLedger(_policy(), EvidenceLedger())


# ─── SutStateTracker ───


def test_tracker_idle_starts_from_second_observation() -> None:
    tracker = SutStateTracker()
    tracker.observe(False, "state-a")
    assert tracker.idle_for_s() is None  # 单次观察无法界定「持续」
    time.sleep(0.01)
    tracker.observe(False, "state-a")
    idle = tracker.idle_for_s()
    assert idle is not None and idle >= 0.01  # 摘要未变 → 空闲计时增长


def test_tracker_change_resets_idle_clock() -> None:
    tracker = SutStateTracker()
    tracker.observe(False, "state-a")
    time.sleep(0.01)
    tracker.observe(False, "state-a")
    time.sleep(0.01)
    tracker.observe(False, "state-b")  # 摘要变化 → 计时归零重计
    assert tracker.idle_for_s() < 0.01
    assert tracker.last_change_ts is not None


def test_tracker_keeps_tail_window() -> None:
    tracker = SutStateTracker()
    for i in range(30):
        tracker.observe(False, f"state-{i}")
    assert len(tracker.observations) == 20
    assert tracker.last_values_text == "state-29"
    assert tracker.last_busy is False


# ─── 产物候选提取 ───


def test_extract_candidates_paths_and_urls() -> None:
    text = (
        "课件已生成：/workspace/out/一元二次方程课件.pdf 和 output/课件.md，"
        "另见 https://sut.example.com/files/report.docx?q=1 下载。"
    )
    assert extract_artifact_candidates([text]) == [
        "/workspace/out/一元二次方程课件.pdf",
        "output/课件.md",
        "https://sut.example.com/files/report.docx?q=1",
    ]


def test_extract_candidates_dedupes_and_caps() -> None:
    text = " ".join(f"output/a{i}.pdf" for i in range(10))
    candidates = extract_artifact_candidates([text, "output/a0.pdf 复现"])
    assert len(candidates) == 5
    assert candidates[0] == "output/a0.pdf"


def test_extract_candidates_ignores_noise() -> None:
    # 无路径分隔符的裸提及、无扩展名路径、纯 URL 无文档扩展名都不算候选
    text = "提到了 md 和 pdf 格式；日志在 /var/log/app；主页 https://sut.example.com/welcome"
    assert extract_artifact_candidates([text]) == []


# ─── 指令摘要 ───


def test_instruction_digest_from_str_and_dict() -> None:
    assert instruction_digest("生成课件") == "生成课件"
    assert instruction_digest({"instruction": "生成课件", "intent": "x"}) == "生成课件"
    assert instruction_digest({"subject": "数学"}) == "数学"
    assert instruction_digest(123) == ""


# ─── build_briefing ───


def test_briefing_full_fields_after_activity() -> None:
    ledger = _ledger()
    assert ledger.authorize("dispatch") is None  # 放行并记账（消耗 1 次 SUT 调用）
    ledger.record("dispatch", "ok", duration_s=1.0, summary="success")  # 工具执行后补证据
    tracker = SutStateTracker()
    tracker.observe(True, "writing")
    time.sleep(0.01)
    tracker.observe(False, "output/课件.pdf ready")
    last_run = {
        "status": "success",
        "text": "课件完成，路径 /workspace/out/课件.pdf",
        "input": "生成初二《一元二次方程》课件",
        "pending": None,
    }

    briefing = build_briefing(ledger=ledger, tracker=tracker, last_run=last_run)

    assert briefing["objective"] == "生成初二《一元二次方程》课件"
    assert briefing["resources"]["sut_calls"] == "7/8"  # 剩余/上限
    assert briefing["resources"]["wall_remaining_s"] == 1500
    assert briefing["sut_state"]["thread_busy"] is False
    assert briefing["sut_state"]["artifact_candidates"] == [
        "/workspace/out/课件.pdf",  # 来自 last_run.text
        "output/课件.pdf",  # 来自 tracker 观察摘要
    ]
    assert "dispatch ok" in briefing["sut_state"]["activity"]
    # hint 纯事实拼装：状态未变化时长 + 产物候选计数
    assert briefing["arbitration"]["hint"].startswith("观察到的状态已 ")
    assert briefing["arbitration"]["hint"].endswith("；产物候选 2 项")
    assert "complete/progressing/stalled/unknown" in briefing["arbitration"]["standard"]
    assert briefing["last_result_digest"].startswith("课件完成")


def test_briefing_graceful_without_observations() -> None:
    briefing = build_briefing(ledger=_ledger(), tracker=None, last_run=None)
    assert briefing["sut_state"]["thread_busy"] is None
    assert briefing["sut_state"]["idle_for_s"] is None
    assert briefing["sut_state"]["artifact_candidates"] == []
    assert briefing["sut_state"]["activity"] == ""
    assert briefing["objective"] == ""
    assert briefing["last_result_digest"] == ""
    assert "尚无" in briefing["arbitration"]["hint"]


def test_briefing_size_bounded() -> None:
    """超长 SUT 文本/指令被截断——简报是每轮上下文税，不设防吃掉工具结果窗口。"""
    last_run = {
        "status": "success",
        "text": "长" * 5000,
        "input": "指令" * 1000,
        "pending": None,
    }
    briefing = build_briefing(ledger=_ledger(), tracker=None, last_run=last_run)
    total = len(str(briefing["last_result_digest"])) + len(str(briefing["objective"]))
    assert total <= 300
