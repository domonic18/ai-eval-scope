"""SUT 终态交付合同单测（arch/16 §4.6，Phase 2.3）。

覆盖：终局交付提取与终态分类（合同二）、交付物渲染（合同三）、
可评估性守卫（合同四）、24 格防回归矩阵（3 通道形态 × 4 类终态 ×
2 类会话命运）。种子用例对齐 run 20260916_074046 三根因。
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from agent_eval.agent.executor.package_writer import (
    ensure_answer_file,
    guard_deliverable,
    guard_evaluable_abort,
)
from agent_eval.agent.executor.terminal import (
    classify_terminal_result,
    classify_thread_state,
    final_delivery,
    output_has_content,
    render_deliverable,
)
from agent_eval.core.types import TerminalKind

# ─── 合同二：final_delivery 终局交付提取 ────────────────────────────────────────


def test_final_delivery_text_final_sut_returns_answer() -> None:
    """text 收尾 SUT：最后一条带文本的 ai 消息即交付，via=text。"""
    messages = [
        {"role": "human", "content": "找视频"},
        {"role": "ai", "content": [{"type": "text", "text": "我先检索"}]},
        {"role": "ai", "content": [{"type": "text", "text": "找到了 5 个视频"}]},
    ]
    text, via = final_delivery(messages)
    assert (text, via) == ("找到了 5 个视频", "text")


def test_final_delivery_tool_call_only_does_not_land_broadcast() -> None:
    """tool_call 交付（sem_002 根因）：文本块之后全是工具活动 → 摘要而非过期播报。"""
    messages = [
        {"role": "human", "content": "找概念辨析资料"},
        {"role": "ai", "content": [{"type": "text", "text": "我来帮你在知识库里检索"}]},
        {
            "role": "ai",
            "content": [],
            "tool_calls": [
                {"name": "knowledge_search", "args": {"query": "温度 热量 内能"}},
                {"name": "deliver", "args": {"note": "推荐两份"}},
            ],
        },
        {"role": "tool", "content": "命中 20 个文件：内能教案8.docx …"},
    ]
    text, via = final_delivery(messages)
    assert via == "tool_digest"
    assert "我来帮你在知识库里检索" not in text  # 过期播报不落交付
    assert "knowledge_search" in text and "命中 20 个文件" in text


def test_final_delivery_openai_function_shape_supported() -> None:
    """OpenAI function 形态的 tool_calls 同样可提取（兼容双形态）。"""
    messages = [
        {"role": "ai", "content": [{"type": "text", "text": "开场白"}]},
        {
            "role": "ai",
            "tool_calls": [{"function": {"name": "search", "arguments": '{"q": "x"}'}}],
        },
        {"role": "tool", "content": "result-ok"},
    ]
    text, via = final_delivery(messages)
    assert via == "tool_digest"
    assert "search" in text and "result-ok" in text


def test_final_delivery_no_messages() -> None:
    assert final_delivery([]) == ("", "none")
    assert final_delivery(None) == ("", "none")


def test_final_delivery_digest_tail_kept_within_budget() -> None:
    """超预算摘要保尾截断：越靠后越接近交付时刻。"""
    messages = [
        {"role": "ai", "content": [{"type": "text", "text": "开场白"}]},
        {
            "role": "ai",
            "tool_calls": [{"name": f"t{i}", "args": {"pad": "x" * 300}} for i in range(30)],
        },
    ]
    text, via = final_delivery(messages)
    assert via == "tool_digest"
    assert len(text) <= 2000
    assert "t29" in text  # 尾部（最后一次调用）保留
    assert "t0(" not in text  # 头部被截掉


# ─── 合同二：classify_thread_state / classify_terminal_result ──────────────────


def test_classify_thread_state_interrupt_pending_is_first_class_terminal() -> None:
    """反问挂起（neg_001 形态：next 非空 + interrupt 挂起）→ 一等终态。"""
    state = {
        "next": ["tools"],
        "tasks": [
            {
                "interrupts": [
                    {
                        "id": "int-1",
                        "value": {
                            "type": "ask_question",
                            "questions": [
                                {
                                    "question": "怎么处理?",
                                    "options": [{"value": "原创", "description": ""}],
                                }
                            ],
                        },
                    }
                ]
            }
        ],
        "values": {
            "messages": [{"role": "ai", "content": [{"type": "text", "text": "我先检索一下"}]}]
        },
    }
    obs = classify_thread_state(state)
    assert obs.kind is TerminalKind.INTERRUPT_PENDING
    assert obs.evaluable
    assert obs.questions and obs.questions[0]["question"] == "怎么处理?"


def test_classify_thread_state_busy_without_signal_is_no_evidence() -> None:
    state = {
        "next": ["agent"],
        "values": {"messages": [{"role": "ai", "content": [{"type": "text", "text": "hi"}]}]},
    }
    assert classify_thread_state(state).kind is TerminalKind.NO_EVIDENCE


def test_classify_thread_state_idle_with_messages_is_delivered() -> None:
    state = {
        "next": [],
        "values": {"messages": [{"role": "ai", "content": [{"type": "text", "text": "完成"}]}]},
    }
    obs = classify_thread_state(state)
    assert obs.kind is TerminalKind.DELIVERED
    assert obs.text == "完成"


def test_classify_thread_state_idle_empty_thread_is_no_evidence() -> None:
    assert classify_thread_state({"next": [], "values": {}}).kind is TerminalKind.NO_EVIDENCE


def test_classify_terminal_result_media001_shape_is_evaluable() -> None:
    """media_001 形态：会话崩但 SUT 完整交付（status=success + 长文本）→ 可评估。"""
    last_run = {
        "status": "success",
        "thread_id": "th-1",
        "text": "找到了……（3425B 完整 MP4 推荐）",
        "input": "找视频",
        "pending": None,
        "output": None,
    }
    assert classify_terminal_result(last_run).kind is TerminalKind.DELIVERED
    assert classify_terminal_result(last_run).evaluable


def test_classify_terminal_result_shapes() -> None:
    questions = [{"question": "q", "options": []}]
    cases: list[tuple[dict[str, Any] | None, TerminalKind, bool]] = [
        (None, TerminalKind.NO_EVIDENCE, False),
        ({}, TerminalKind.NO_EVIDENCE, False),
        (
            {"status": "interrupted", "text": "播报", "pending": {"questions": questions}},
            TerminalKind.INTERRUPT_PENDING,
            True,
        ),
        (
            {"status": "success", "text": "", "output": {"files": ["a.md"]}},
            TerminalKind.DELIVERED,
            True,
        ),
        ({"status": "timeout"}, TerminalKind.SUT_FAILED, False),
        ({"status": "failed", "text": ""}, TerminalKind.SUT_FAILED, False),
        ({"status": "running", "text": ""}, TerminalKind.NO_EVIDENCE, False),
    ]
    for last_run, kind, evaluable in cases:
        obs = classify_terminal_result(last_run)
        assert obs.kind is kind, last_run
        assert obs.evaluable is evaluable, last_run


def test_output_has_content() -> None:
    assert not output_has_content(None)
    assert not output_has_content({})
    assert not output_has_content({"text": ""})
    assert output_has_content({"text": "x"})
    assert output_has_content({"files": ["a"]})
    assert output_has_content(["a"])
    assert output_has_content("x")


# ─── 合同三：交付物渲染 ─────────────────────────────────────────────────────────


def test_render_deliverable_full_triple() -> None:
    obs = classify_terminal_result(
        {
            "status": "interrupted",
            "text": "我先检索一下",
            "delivery_via": "text",
            "pending": {
                "questions": [
                    {
                        "question": "怎么处理?",
                        "options": [{"value": "原创", "description": "现场写一份"}],
                    }
                ]
            },
        }
    )
    rendered = render_deliverable(obs)
    assert "我先检索一下" in rendered
    assert "反问待应答" in rendered
    assert "**Q1**：怎么处理?" in rendered
    assert "- 原创 — 现场写一份" in rendered


def test_render_deliverable_tool_digest_labelled() -> None:
    obs = classify_terminal_result(
        {"status": "success", "text": "→ 调用 deliver(...)", "delivery_via": "tool_digest"}
    )
    rendered = render_deliverable(obs)
    assert "工具调用交付" in rendered
    assert "→ 调用 deliver(...)" in rendered


def test_render_deliverable_structured_output_json_block() -> None:
    obs = classify_terminal_result({"status": "success", "text": "", "output": {"files": ["a.md"]}})
    rendered = render_deliverable(obs)
    assert "结构化交付" in rendered and '"files"' in rendered and "a.md" in rendered


def test_render_deliverable_empty_obs_is_empty() -> None:
    assert render_deliverable(classify_terminal_result(None)) == ""


# ─── 合同三/四：守卫与物化 ──────────────────────────────────────────────────────


def _write_manifest(pkg: Path, status: str) -> None:
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "manifest.json").write_text(
        json.dumps({"status": status, "content_hash": ""}), encoding="utf-8"
    )


def _read_manifest(pkg: Path) -> dict[str, Any]:
    return json.loads((pkg / "manifest.json").read_text(encoding="utf-8"))


def _read_metadata(pkg: Path) -> dict[str, Any]:
    """守卫早退时不写 metadata.json——缺失视为空（与 _load_json_object 同语义）。"""
    path = pkg / "metadata.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def test_ensure_answer_file_renders_interrupt_questions(tmp_path: Path) -> None:
    """neg_001 形态：播报 + 反问一并物化——answer.md 不再冻结在首句播报。"""
    last_run = {
        "status": "interrupted",
        "text": "我先在教学知识库里检索一下",
        "pending": {
            "questions": [
                {
                    "question": "资料怎么处理?",
                    "options": [{"value": "原创编写", "description": "现场写"}],
                }
            ]
        },
    }
    ensure_answer_file(tmp_path, last_run)
    answer = (tmp_path / "output" / "answer.md").read_text(encoding="utf-8")
    assert "我先在教学知识库里检索一下" in answer
    assert "反问待应答" in answer and "原创编写" in answer


def test_ensure_answer_file_empty_evidence_writes_nothing(tmp_path: Path) -> None:
    assert ensure_answer_file(tmp_path, None) == ""
    assert not (tmp_path / "output" / "answer.md").exists()


def test_guard_deliverable_marks_degraded_on_missing_evidence(tmp_path: Path) -> None:
    """无交付证据而对话非空 → degraded_evidence 留痕（纵深防御）。"""
    _write_manifest(tmp_path, "failed")
    (tmp_path / "transcript.md").write_text("有完整对话过程", encoding="utf-8")
    guard_deliverable(tmp_path, None)
    metadata = json.loads((tmp_path / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["degraded_evidence"] is True


def test_guard_deliverable_silent_when_delivered_or_output_present(tmp_path: Path) -> None:
    _write_manifest(tmp_path, "success")
    (tmp_path / "transcript.md").write_text("对话", encoding="utf-8")
    guard_deliverable(tmp_path, {"status": "success", "text": "有交付"})
    assert "degraded_evidence" not in _read_metadata(tmp_path)
    # SUT 产物文件在列（交付走文件而非 answer）→ 同样不算 degraded
    (tmp_path / "output").mkdir()
    (tmp_path / "output" / "doc.md").write_text("# 产物", encoding="utf-8")
    guard_deliverable(tmp_path, None)
    assert "degraded_evidence" not in _read_metadata(tmp_path)


def test_guard_evaluable_abort_flips_only_evaluable(tmp_path: Path) -> None:
    """合同四：有交付证据才翻回 success；无证据 / SUT 失败保持 failed。"""
    for last_run, expect_success in [
        ({"status": "success", "text": "完整交付"}, True),
        (
            {
                "status": "interrupted",
                "text": "播报",
                "pending": {"questions": [{"question": "q"}]},
            },
            True,
        ),
        (None, False),
        ({"status": "timeout"}, False),
    ]:
        pkg = tmp_path / f"case-{int(expect_success)}-{id(last_run)}"
        _write_manifest(pkg, "failed")
        guard_evaluable_abort(pkg, last_run)
        status = _read_manifest(pkg)["status"]
        assert (status == "success") is expect_success, last_run
        metadata = _read_metadata(pkg)
        assert metadata.get("guard_evaluable_abort", False) is expect_success


def test_guard_evaluable_abort_skips_success_manifest(tmp_path: Path) -> None:
    _write_manifest(tmp_path, "success")
    guard_evaluable_abort(tmp_path, {"status": "success", "text": "x"})
    assert _read_manifest(tmp_path)["status"] == "success"


# ─── 24 格防回归矩阵（3 形态 × 4 终态 × 2 会话命运） ────────────────────────────


def _commands_last_run(ending: str) -> dict[str, Any] | None:
    if ending == "text_final":
        return {"status": "success", "text": "最终答案", "pending": None}
    if ending == "tool_call_delivery":
        return {
            "status": "success",
            "text": "→ 调用 deliver(...)\n← 交付内容",
            "delivery_via": "tool_digest",
            "pending": None,
        }
    if ending == "interrupt_pending":
        return {
            "status": "interrupted",
            "text": "我先检索一下",
            "pending": {"questions": [{"question": "怎么办?", "options": []}]},
        }
    return None  # timeout_no_evidence：异常先于记账，last_run 缺失


def _runs_last_run(ending: str) -> dict[str, Any] | None:
    if ending == "text_final":
        return {"status": "success", "text": "最终答案", "output": {"text": "最终答案"}}
    if ending == "tool_call_delivery":
        return {
            "status": "success",
            "text": "",
            "output": {"files": ["a.md"], "urls": ["https://x"]},
        }
    return None  # runs 形态无 interrupt 概念 / 超时先于记账


def _generic_last_run(ending: str) -> dict[str, Any] | None:
    if ending == "text_final":
        return {"status": "success", "text": "正文", "output": {"answer": "正文"}}
    if ending == "tool_call_delivery":
        return {"status": "success", "text": "", "output": {"files": ["b.pdf"]}}
    if ending == "interrupt_pending":
        return None  # generic_http 无 interrupt 概念
    return {"status": "timeout"}  # generic 通道超时有显式 status


_BUILDERS: dict[str, Callable[[str], dict[str, Any] | None]] = {
    "commands": _commands_last_run,
    "runs": _runs_last_run,
    "generic_http": _generic_last_run,
}

# (flavor, ending) → (TerminalKind 值, 可评估, answer.md 必含标记 / None)
_EXPECTED: dict[tuple[str, str], tuple[str, bool, str | None]] = {
    ("commands", "text_final"): ("delivered", True, "最终答案"),
    ("commands", "tool_call_delivery"): ("delivered", True, "工具调用交付"),
    ("commands", "interrupt_pending"): ("interrupt_pending", True, "反问待应答"),
    ("commands", "timeout_no_evidence"): ("no_evidence", False, None),
    ("runs", "text_final"): ("delivered", True, "最终答案"),
    ("runs", "tool_call_delivery"): ("delivered", True, "结构化交付"),
    ("runs", "interrupt_pending"): ("no_evidence", False, None),
    ("runs", "timeout_no_evidence"): ("no_evidence", False, None),
    ("generic_http", "text_final"): ("delivered", True, "正文"),
    ("generic_http", "tool_call_delivery"): ("delivered", True, "结构化交付"),
    ("generic_http", "interrupt_pending"): ("no_evidence", False, None),
    ("generic_http", "timeout_no_evidence"): ("sut_failed", False, None),
}

_ENDINGS = ("text_final", "tool_call_delivery", "interrupt_pending", "timeout_no_evidence")


@pytest.mark.parametrize("flavor", ["commands", "runs", "generic_http"])
@pytest.mark.parametrize(
    "ending,fate", [(ending, fate) for ending in _ENDINGS for fate in ("alive", "crashed")]
)
def test_terminal_matrix_24_cells(tmp_path: Path, flavor: str, ending: str, fate: str) -> None:
    """24 格矩阵：终态分类与可评估性只看证据，与会话命运无关（合同四核心不变量）。

    fate=alive 走正常收尾（作答守卫面），fate=crashed 走 abort 收尾
    （guard_aborted 强制 failed 后 guard_evaluable_abort 按证据复核）——
    两条路径对同一 (flavor, ending) 必须给出相同的可评估结论。
    """
    last_run = _BUILDERS[flavor](ending)
    kind_value, evaluable, marker = _EXPECTED[(flavor, ending)]

    obs = classify_terminal_result(last_run)
    assert obs.kind.value == kind_value, (flavor, ending)
    assert obs.evaluable is evaluable, (flavor, ending)
    answer = render_deliverable(obs)
    if marker is None:
        assert answer == "", (flavor, ending)
    else:
        assert marker in answer, (flavor, ending)

    if fate == "crashed":
        pkg = tmp_path / f"{flavor}-{ending}"
        _write_manifest(pkg, "failed")
        (pkg / "transcript.md").write_text("对话过程", encoding="utf-8")
        guard_evaluable_abort(pkg, last_run)
        assert (_read_manifest(pkg)["status"] == "success") is evaluable, (flavor, ending)
