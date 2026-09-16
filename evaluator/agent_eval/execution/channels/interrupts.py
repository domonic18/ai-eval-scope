"""Agent Protocol 中断提取（thread_commands 拆出，plan/07 G2/G4）——纯函数无 IO。

LangGraph interrupt 结构的识别与诊断：反问挂起提取、未识别类型透出、
ask_question 工具调用 id 留档。通道轮询与协议探测共用。
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any


def _iter_interrupts(state: dict[str, Any] | None) -> list[Any]:
    """收集线程 state 上的全部中断（tasks[].interrupts[] + 顶层兼容位）。"""
    if not isinstance(state, dict):
        return []
    interrupts: list[Any] = []
    for task in state.get("tasks") or []:
        if isinstance(task, dict):
            interrupts.extend(task.get("interrupts") or [])
    if isinstance(state.get("interrupts"), list):
        interrupts.extend(state["interrupts"])
    return interrupts


def pending_ask_questions(
    state: dict[str, Any] | None,
    interrupt_types: Sequence[str] = ("ask_question",),
) -> list[dict[str, Any]]:
    """提取 state 中挂起的反问中断（LangGraph interrupt 结构）。

    结构（2026-09 对 sasan/DeepAgents 实测）：state.next 非空（如 ['tools']），
    state.tasks[].interrupts[] 携带 {"id", "value": {"type": "ask_question",
    "questions": [{"question", "options": [{"value", "description"}], "multiple"?}]}}；
    顶层 state.interrupts 作兼容提取。此前提取缺失——反问被当普通未终态轮询到
    「run 超时」（300s），反问永远到不了评估 Agent。

    interrupt_types：识别为反问挂起的 value.type 集合（sut.interrupt_types 可配）。
    "ask_question" 是 sasan 前端契约而非协议标准——接入新 SUT 按其中断形态扩展
    配置；集合外的中断类型不当作反问（避免把不可应答的人机中断误配成应答载荷），
    由轮询超时诊断透出（unrecognized_interrupt_types）。
    """
    known = set(interrupt_types)
    questions: list[dict[str, Any]] = []
    for interrupt in _iter_interrupts(state):
        if not isinstance(interrupt, dict):
            continue
        value = interrupt.get("value")
        if not isinstance(value, dict) or value.get("type") not in known:
            continue
        for question in value.get("questions") or []:
            if isinstance(question, dict):
                questions.append({**question, "interrupt_id": interrupt.get("id") or ""})
    return questions


def unrecognized_interrupt_types(
    state: dict[str, Any] | None,
    interrupt_types: Sequence[str] = ("ask_question",),
) -> list[str]:
    """线程上出现过但不在识别集内的 interrupt 类型（超时诊断，plan/07 G2）。

    接入新 SUT 时若其中断形态未配进 sut.interrupt_types，症状是「轮询到超时」
    而非清晰失败——把线程上实际挂着的未识别类型写进错误 details，排障第一眼
    即见真因（缺的只是配置，不是协议支持）。
    """
    known = set(interrupt_types)
    seen = {
        str(value.get("type"))
        for interrupt in _iter_interrupts(state)
        if isinstance(interrupt, dict)
        and isinstance((value := interrupt.get("value")), dict)
        and value.get("type")
    }
    return sorted(seen - known)


def ask_question_tool_call_ids(messages: list[dict[str, Any]] | None) -> list[str]:
    """从消息流提取 ask_question 工具调用 id（诊断/留档用，不参与应答载荷）。

    应答载荷是前端同款 ``{"answers": [...]}``（见 respond_input_envelope），
    无需工具调用 id；本函数仅用于 pending 留档与消息形态诊断。
    """
    ids: list[str] = []
    for message in messages or []:
        if not isinstance(message, dict):
            continue
        calls = [c for c in message.get("tool_calls") or [] if isinstance(c, dict)]
        for block in message.get("content") or []:
            if isinstance(block, dict) and block.get("type") == "tool_call":
                calls.append(block)
        for call in calls:
            if call.get("name") == "ask_question" and call.get("id"):
                ids.append(str(call["id"]))
    return ids
