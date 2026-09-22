"""执行对话记录（transcript.md）渲染——纯函数，无实例状态。

从 agent.py 拆出：transcript 是人类可读的过程证据，渲染逻辑
与执行循环/包物化无耦合。单条超长截断（完整原文见 agent_logs 会话日志）。
"""

from __future__ import annotations

import json
from typing import Any

# 单条消息渲染上限——对话记录是可读性过程证据，超长内容（如 SUT
# 全量线程回传）截断；完整原文在 agent_logs 会话日志里
TRANSCRIPT_MESSAGE_MAX_CHARS = 6000


def clip_transcript_text(text: str) -> str:
    if len(text) <= TRANSCRIPT_MESSAGE_MAX_CHARS:
        return text
    return text[:TRANSCRIPT_MESSAGE_MAX_CHARS] + "\n\n……（截断）"


def transcript_message_text(message: dict[str, Any]) -> str:
    """提取消息可展示文本：content 字符串 / 类型块列表仅取 text 块（思考块天然排除）。"""
    if "repr" in message:  # 序列化兜底形态（非 langchain 消息对象）
        return str(message["repr"])
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [
            block.get("text") or ""
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        ]
        return "\n".join(p for p in parts if p.strip())
    if isinstance(content, dict):
        return json.dumps(content, ensure_ascii=False, default=str)
    return ""


def render_transcript_message(message: dict[str, Any]) -> str | None:
    """渲染单条消息为 Markdown 段；无正文且无工具调用返回 None（段内跳过）。"""
    mtype = str(message.get("type", "")).lower()
    text = transcript_message_text(message).strip()
    if mtype == "tool":
        name = message.get("name") or message.get("tool_call_id") or "tool"
        return "\n".join(
            [f"工具结果 · {name}", "", "```", clip_transcript_text(text or "（空）"), "```"]
        )
    body: list[str] = []
    if text:
        label = "任务提示（发起）" if mtype == "human" else "执行 Agent"
        body.extend([label, "", clip_transcript_text(text)])
    for call in message.get("tool_calls") or []:
        if not isinstance(call, dict):
            continue
        body.append("")
        body.append(f"**调用工具 `{call.get('name') or 'unknown'}`**")
        if call.get("args") is not None:
            body.extend(
                [
                    "",
                    "```json",
                    clip_transcript_text(json.dumps(call["args"], ensure_ascii=False, default=str)),
                    "```",
                ]
            )
    return "\n".join(body) if body else None


def build_transcript(
    task_id: str,
    instruction_text: str,
    messages: list[Any],
    *,
    aborted_reason: str | None = None,
) -> str:
    """组装 transcript.md 全文（包根过程证据，与 trace.json 同层）。

    aborted_reason 非 None（异常收尾，图抛异常无会话可恢复）时对话过程
    为空属预期——显式注明中断原因与完整日志位置，避免读包人误判记录丢失。
    """
    lines: list[str] = [
        "# 执行对话记录",
        "",
        f"> 任务 ID: {task_id}。记录执行 Agent 的完整交互过程（不含思考过程），"
        "单条超长内容截断——完整原文见 agent_logs 会话日志。",
        "",
        "## 任务指令",
        "",
        clip_transcript_text(instruction_text),
        "",
        "## 对话过程",
        "",
    ]
    if aborted_reason is not None:
        lines += [
            f"> ⚠️ 会话异常中断：{clip_transcript_text(aborted_reason)}",
            "> 完整过程日志见执行包同目录 agent_logs/agent_"
            f"{task_id}.jsonl（本文件仅渲染正常完成的会话）。",
            "",
        ]
    seq = 0
    for message in messages:
        if not isinstance(message, dict):
            continue
        section = render_transcript_message(message)
        if section is None:
            continue
        seq += 1
        lines.extend([f"### {seq}. {section}", ""])
    return "\n".join(lines)
