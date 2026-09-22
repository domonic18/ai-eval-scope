"""Agent Protocol 消息摘要（thread_commands 拆出）——纯函数无 IO。

Agent 协议线程的 messages 形态整形：取最终回答文本、压缩整表摘要。
执行器（protocol_tools）与通道轮询（thread_commands）共用。
"""

from __future__ import annotations

import json
from typing import Any

AI_ROLES = frozenset({"ai", "assistant"})
COMPACT_TEXT_MAX_CHARS = 800  # 消息摘要单条文本上限（整表仍受 bounded_result 截断约束）


def ai_message_text(message: dict[str, Any]) -> str:
    """单条 ai 消息的文本（content 为类型块列表，跳过 reasoning；无文本返回空串）。"""
    if message.get("role") not in AI_ROLES and message.get("type") not in AI_ROLES:
        return ""
    content = message.get("content")
    parts: list[str] = []
    if isinstance(content, str):
        parts.append(content)
    elif isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text") or "")
    return "\n".join(p for p in parts if p.strip())


def final_ai_text(messages: list[dict[str, Any]] | None) -> str:
    """取最后一条含非空文本的 ai 消息（content 为类型块列表，跳过 reasoning）。"""
    for message in reversed(messages or []):
        if not isinstance(message, dict):
            continue
        text = ai_message_text(message)
        if text.strip():
            return text
    return ""


def has_ai_message_from(messages: list[dict[str, Any]] | None, start: int) -> bool:
    """messages[start:] 起是否出现过 ai 消息（内容形态不限：text / 工具调用块均算）。

    终态判定用「新增 ai 消息」而非「尾随 ai 文本」：以工具调用收尾的 SUT
    （写完产物即结束、无结束语）曾因无 text 块被判「未终态」，空转轮询烧满
    超时预算后误报 run 超时（2026-09-11 实测事故）。
    """
    return any(
        message.get("role") in AI_ROLES or message.get("type") in AI_ROLES
        for message in (messages or [])[start:]
    )


def compact_messages(messages: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """消息摘要：丢弃 reasoning/thinking 块与超长文本，保留对话骨架。

    DeepAgents 族 SUT 单条 ai 消息可携带数万字符 reasoning 块且排布在 text 之前
    ——整表 JSON 化再截断会把真正的回答/反问截掉，执行 Agent 只看到推理噪声
    （2026-09 实测：6 万字符 reasoning 挤占 4000 字符窗口，任务连烧 3 轮要求
    SUT「不要截断」——截断发生在评测器侧而非 SUT）。摘要按消息保留文本与
    工具调用骨架。
    """
    out: list[dict[str, Any]] = []
    for message in messages or []:
        if not isinstance(message, dict):
            continue
        compact: dict[str, Any] = {"role": message.get("type") or message.get("role") or "unknown"}
        texts: list[str] = []
        content = message.get("content")
        if isinstance(content, str):
            texts.append(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, str):
                    texts.append(block)
                elif not isinstance(block, dict):
                    continue
                elif block.get("type") in ("text", "tool_result"):
                    text = block.get("text") or block.get("content") or ""
                    texts.append(text if isinstance(text, str) else json.dumps(text, default=str))
                elif block.get("type") == "tool_call":
                    compact.setdefault("tool_calls", []).append(
                        {
                            "name": block.get("name"),
                            "id": block.get("id"),
                            "args": json.dumps(block.get("args"), ensure_ascii=False, default=str)[
                                :COMPACT_TEXT_MAX_CHARS
                            ],
                        }
                    )
        for call in message.get("tool_calls") or []:
            if isinstance(call, dict):
                compact.setdefault("tool_calls", []).append(
                    {
                        "name": call.get("name"),
                        "id": call.get("id"),
                        "args": json.dumps(call.get("args"), ensure_ascii=False, default=str)[
                            :COMPACT_TEXT_MAX_CHARS
                        ],
                    }
                )
        joined = "\n".join(t for t in texts if t and t.strip())[:COMPACT_TEXT_MAX_CHARS]
        if joined:
            compact["content"] = joined
        if len(compact) > 1:
            out.append(compact)
    return out
