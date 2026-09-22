"""SUT 终态交付合同——纯函数无 IO。

run 20260916_074046 三根因的机械归一：观测全量入账（合同一）、终态分类
（合同二 terminality 分级）、交付物渲染（合同三）。SUT 的终态交付物是
``{text, output, questions}`` 三元而不是 text 一个字段；终态形态归一为
TerminalKind 四枚举，interrupt_pending 是一等终态（反问即 SUT 显式收尾
信号），settle 空转只对 no_evidence 生效。
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from agent_eval.agent.core.tools import truncate
from agent_eval.core.types import TerminalKind
from agent_eval.execution.channels.interrupts import pending_ask_questions
from agent_eval.execution.channels.message_digest import ai_message_text

# 台账观测载荷截断上限（全量在 trace，台账只留可读摘要）
OBSERVATION_TEXT_MAX_CHARS = 800
# 工具交付摘要总预算（保尾）与单行上限
DELIVERY_DIGEST_MAX_CHARS = 2000
DELIVERY_DIGEST_LINE_MAX_CHARS = 400

_AI_ROLES = frozenset({"ai", "assistant"})
_TOOL_ROLES = frozenset({"tool", "tool_call_result"})


def output_has_content(output: Any) -> bool:
    """结构化 output 是否携带真实内容（``{"text": ""}`` 类空壳不算）。"""
    if output is None:
        return False
    if isinstance(output, dict):
        return any(value for value in output.values())
    if isinstance(output, (list, str)):
        return bool(output)
    return True


def _call_name_args(call: dict[str, Any]) -> tuple[str, str]:
    """工具调用条目的 (名称, 参数 JSON)——兼容 OpenAI function / langchain args 形态。"""
    fn = call.get("function")
    if isinstance(fn, dict):
        args: Any = fn.get("arguments")
    else:
        args = call.get("args") if call.get("args") is not None else call.get("input")
    name = (call.get("name") or (fn.get("name") if isinstance(fn, dict) else "")) or "tool"
    if not isinstance(args, str):
        args = json.dumps(args, ensure_ascii=False, default=str)
    return str(name), args


def _message_tool_calls(message: dict[str, Any]) -> list[tuple[str, str]]:
    """AI 消息上的工具调用（顶层 tool_calls + content 块两种形态）。"""
    calls: list[tuple[str, str]] = []
    for call in message.get("tool_calls") or []:
        if isinstance(call, dict):
            calls.append(_call_name_args(call))
    for block in message.get("content") or []:
        if isinstance(block, dict) and block.get("type") == "tool_call":
            calls.append(_call_name_args(block))
    return calls


def final_delivery(
    messages: list[dict[str, Any]] | None,
    *,
    max_chars: int = DELIVERY_DIGEST_MAX_CHARS,
    line_max: int = DELIVERY_DIGEST_LINE_MAX_CHARS,
) -> tuple[str, str]:
    """终局交付提取（合同二）：返回 ``(交付文本, via)``。

    - via="text"：最后一条 AI 消息自带文本块——文本即交付，原文返回；
    - via="tool_digest"：最后文本块之后还有 tool_call-only 的 AI 消息——SUT
      以工具调用交付（无文本收尾），任何在手文本都是过期播报（run
      20260916_074046 sem_002：answer.md 冻结在首句播报 81B）——渲染尾部
      工具调用/结果摘要，保尾截断；
    - via="none"：无 AI 消息。
    """
    msgs = [m for m in (messages or []) if isinstance(m, dict)]
    last_ai = -1
    last_text_ai = -1
    for i, message in enumerate(msgs):
        role = message.get("role") or message.get("type")
        if role not in _AI_ROLES:
            continue
        last_ai = i
        if ai_message_text(message).strip():
            last_text_ai = i
    if last_ai < 0:
        return "", "none"
    if last_text_ai == last_ai:
        return ai_message_text(msgs[last_ai]).strip(), "text"
    # 尾部工具活动（最后一条文本消息之后的全部消息）
    lines: list[str] = []
    for message in msgs[last_text_ai + 1 :]:
        role = message.get("role") or message.get("type")
        if role in _AI_ROLES:
            for name, args in _message_tool_calls(message):
                lines.append(f"→ 调用 {name}({truncate(args, line_max)})")
        elif role in _TOOL_ROLES or role == "tool":
            content = message.get("content")
            text = (
                content
                if isinstance(content, str)
                else json.dumps(content, ensure_ascii=False, default=str)
            )
            if text.strip():
                lines.append(f"← {truncate(text.strip(), line_max)}")
    if not lines:
        return ai_message_text(msgs[last_text_ai]).strip() if last_text_ai >= 0 else "", "text"
    digest = "\n".join(lines)
    if len(digest) > max_chars:
        digest = digest[-max_chars:]  # 保尾：越靠后越接近交付时刻
    return digest, "tool_digest"


@dataclass
class TerminalObservation:
    """SUT 终态观测（合同一/二归一产物）：kind + 交付三元。"""

    kind: TerminalKind
    text: str = ""
    output: Any = None
    questions: list[dict[str, Any]] | None = None
    # 交付通道：text=SUT 文本收尾；tool_digest=工具调用交付（text 为摘要）
    via: str = "text"

    @property
    def evaluable(self) -> bool:
        """有交付证据即可评估（合同四）：SUT 交付/反问 ≠ 执行会话未崩。"""
        return self.kind in (TerminalKind.DELIVERED, TerminalKind.INTERRUPT_PENDING)


def classify_thread_state(
    state: dict[str, Any] | None,
    *,
    interrupt_types: Sequence[str] = ("ask_question",),
    output: Any = None,
) -> TerminalObservation:
    """commands 线程态终态分类（refresh_final_state 的 settle 判据单点）。

    - 反问挂起（``pending_ask_questions`` 命中）→ INTERRUPT_PENDING：SUT 显式
      收尾信号，单采样立即返回（对齐 ``_poll_state`` 既有语义）——interrupt
      线程 ``next`` 永不清空，此前 settle 只看 ``next`` 会空转满超时（run
      20260916_074046 neg_001：空转 120s 后带旧值早退）；
    - 空闲 + 有消息/结构化 output → DELIVERED；
    - 其余（无任何终态证据）→ NO_EVIDENCE：settle 唯一的等待对象。
    """
    state = state or {}
    questions = pending_ask_questions(state, interrupt_types)
    values = state.get("values") or {}
    messages = values.get("messages")
    if questions:
        text, via = final_delivery(messages)
        return TerminalObservation(
            kind=TerminalKind.INTERRUPT_PENDING,
            text=text,
            output=output,
            questions=questions,
            via=via,
        )
    idle = not (state.get("next") or [])
    if idle and (messages or output_has_content(output)):
        text, via = final_delivery(messages)
        return TerminalObservation(kind=TerminalKind.DELIVERED, text=text, output=output, via=via)
    return TerminalObservation(kind=TerminalKind.NO_EVIDENCE)


def classify_terminal_result(last_run: dict[str, Any] | None) -> TerminalObservation:
    """last_run / run 返回值终态分类（ensure_answer_file / 守卫的判据单点）。"""
    if not last_run:
        return TerminalObservation(kind=TerminalKind.NO_EVIDENCE)
    text = str(last_run.get("text") or "")
    output = last_run.get("output")
    pending = last_run.get("pending")
    questions = (pending or {}).get("questions")
    via = last_run.get("delivery_via") or "text"
    if questions:
        return TerminalObservation(
            kind=TerminalKind.INTERRUPT_PENDING,
            text=text,
            output=output,
            questions=questions,
            via=via,
        )
    if text.strip() or output_has_content(output):
        return TerminalObservation(kind=TerminalKind.DELIVERED, text=text, output=output, via=via)
    if last_run.get("status") in ("failed", "error", "timeout"):
        return TerminalObservation(kind=TerminalKind.SUT_FAILED, text=text, output=output, via=via)
    return TerminalObservation(kind=TerminalKind.NO_EVIDENCE)


def render_questions(questions: list[dict[str, Any]] | None) -> str:
    """反问题单渲染（选项 + 描述逐条列出，供评估判读 SUT 的诚实反问行为）。"""
    parts: list[str] = []
    for i, question in enumerate(questions or [], 1):
        lines = [f"**Q{i}**：{question.get('question') or ''}"]
        for option in question.get("options") or []:
            if isinstance(option, dict):
                desc = f" — {option['description']}" if option.get("description") else ""
                lines.append(f"- {option.get('value') or ''}{desc}")
        parts.append("\n".join(lines))
    return "\n\n".join(parts)


def render_deliverable(obs: TerminalObservation) -> str:
    """终态交付物渲染（合同三）：三元全量渲染，宁可重复不可丢失。

    - text（via=tool_digest 时标注「工具调用交付摘要」——文本是过期播报风险区）；
    - output 结构化交付（generic markdown，JSON 代码块）；
    - questions 显式标注「反问待应答」——评估侧未代答，属 SUT 真实行为。
    """
    sections: list[str] = []
    text = (obs.text or "").strip()
    if text:
        if obs.via == "tool_digest":
            sections.append(
                "## SUT 经工具调用交付（无文本收尾，以下为尾部工具活动摘要）\n\n" + text
            )
        else:
            sections.append(text)
    if output_has_content(obs.output):
        payload = json.dumps(obs.output, ensure_ascii=False, indent=2, default=str)
        sections.append(f"## 结构化交付\n\n```json\n{payload}\n```")
    if obs.kind is TerminalKind.INTERRUPT_PENDING and obs.questions:
        sections.append(
            "## ⏸ 反问待应答（SUT 等待用户选择，评估侧未代答）\n\n"
            + render_questions(obs.questions)
        )
    return "\n\n".join(sections)


def log_sut_observation(ledger: Any, *, source: str, run: dict[str, Any] | None) -> None:
    """合同一：SUT 观测全量入台账（载荷截断，全量在 trace/answer）。

    两个工具面（protocol_tools / http_tools）共用：last_run 单槽保留
    output/pending 之后，观测载荷以 ``sut_observation`` 事件同步入
    EvidenceLedger——台账从「动作元数据」升级为「含观测载荷」，失败包
    三问自解释覆盖到「SUT 到底交付了什么」。
    """
    if ledger is None or getattr(ledger, "evidence", None) is None:
        return
    obs = classify_terminal_result(run)
    output = (run or {}).get("output")
    ledger.evidence.log(
        "sut_observation",
        source=source,
        status=(run or {}).get("status"),
        thread_id=(run or {}).get("thread_id"),
        terminal_kind=obs.kind.value,
        text=truncate(str((run or {}).get("text") or ""), OBSERVATION_TEXT_MAX_CHARS) or None,
        output=(
            truncate(
                json.dumps(output, ensure_ascii=False, default=str), OBSERVATION_TEXT_MAX_CHARS
            )
            if output_has_content(output)
            else None
        ),
        questions=len(obs.questions or ()),
    )
