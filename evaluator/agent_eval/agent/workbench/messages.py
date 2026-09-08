"""langgraph 消息面 — 撞线判定 / 孤儿修复 / 文本提取 / 工具事件 / 流收集 / salvage。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

try:  # langgraph 属 [agent] extra；缺席（CI 纯单测）时撞线判定恒 False
    from langgraph.errors import GraphRecursionError as _GraphRecursionError
except ImportError:  # pragma: no cover
    _GraphRecursionError = None  # type: ignore[assignment,misc]


def is_recursion_limit(exc: BaseException) -> bool:
    """recursion_limit 撞线判定（langgraph 缺席时恒 False）。"""
    return _GraphRecursionError is not None and isinstance(exc, _GraphRecursionError)


# salvage 合成的失败 ToolMessage 正文（同时告知模型该调用未完成，可重发）
_ORPHAN_TOOL_NOTE = "（会话在此被打断，未执行完——如仍需该结果请重新调用）"


def _synthetic_tool_message(call_id: str, name: str) -> Any:
    """构造孤儿 tool_call 的失败 ToolMessage（langchain_core 缺席时退化占位对象）。"""
    try:
        from langchain_core.messages import ToolMessage
    except ImportError:  # pragma: no cover — 单测 mock 环境
        from types import SimpleNamespace

        return SimpleNamespace(
            type="tool", tool_call_id=call_id, name=name, content=_ORPHAN_TOOL_NOTE
        )
    return ToolMessage(content=_ORPHAN_TOOL_NOTE, tool_call_id=call_id, name=name)


def repair_orphan_tool_calls(messages: list[Any]) -> list[Any]:
    """半途消息的孤儿 tool_call 修复：无结果的调用合成失败 ToolMessage。

    孤儿 tool_call 会破坏图（AI 发起调用后没有配对 ToolMessage，下次调模型
    API 直接 400）——salvage 并入宿主历史前必须补齐，进度才真正可续。
    """
    repaired = list(messages)
    pending: dict[str, str] = {}  # tool_call_id → name（含序）
    for msg in repaired:
        mtype = getattr(msg, "type", "")
        if mtype == "ai":
            for call in getattr(msg, "tool_calls", None) or []:
                call_id = str(call.get("id", "") if isinstance(call, dict) else "")
                if call_id:
                    pending[call_id] = str(call.get("name", "") if isinstance(call, dict) else "")
        elif mtype == "tool":
            pending.pop(str(getattr(msg, "tool_call_id", "")), None)
    repaired.extend(_synthetic_tool_message(call_id, name) for call_id, name in pending.items())
    return repaired


def text_from_content(content: Any) -> str:
    """content → 纯文本：str 原样；Anthropic 风格 content blocks 只取 type=text 段。

    KIMI / Claude 系模型 content 为 ``[{"type": "thinking"|"text", ...}, ...]`` 列表
    （thinking 段不并入回复文本）。
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            str(block.get("text", ""))
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
    return ""


def last_ai_text(messages: list[Any]) -> str:
    """取消息列表中最后一条 AI 文本（计划/总结展示用）。"""
    for msg in reversed(messages):
        text = text_from_content(getattr(msg, "content", ""))
        if getattr(msg, "type", "") == "ai" and text.strip():
            return text.strip()
    return ""


def emit_tool_events(updates: dict[str, Any], emit: Callable[[dict[str, Any]], None]) -> None:
    """把 langgraph ``updates`` 增量转成工具进度事件（tool_start / tool_end）。

    - model 节点 AIMessage.tool_calls → tool_start（name + args）
    - tools 节点 ToolMessage → tool_end（ok + 原始输出串，CLI 自行解析 error/staged）
    """
    for delta in updates.values():
        if not isinstance(delta, dict):
            continue
        for msg in delta.get("messages") or []:
            mtype = getattr(msg, "type", "")
            if mtype == "ai":
                for call in getattr(msg, "tool_calls", None) or []:
                    emit(
                        {
                            "type": "tool_start",
                            "name": call.get("name", ""),
                            "args": call.get("args") or {},
                        }
                    )
            elif mtype == "tool":
                content = getattr(msg, "content", "")
                status = getattr(msg, "status", "success")
                emit(
                    {
                        "type": "tool_end",
                        "name": getattr(msg, "name", "") or "",
                        "ok": status != "error",
                        "output": content if isinstance(content, str) else str(content),
                    }
                )


async def stream_collect(
    graph: Any,
    messages: list[Any],
    config: dict[str, Any],
    on_event: Callable[[dict[str, Any]], None],
) -> dict[str, Any]:
    """流式图调用（astream 三模）：增量 token / 工具事件 / 收集最终状态。

    ``messages`` 模式发 token / thinking / tool_args 增量事件；``updates`` 模式转
    tool_start/tool_end；``values`` 模式收集最终状态。无 values 事件（流提前中断）
    时回退一次性 ainvoke。
    """
    final: dict[str, Any] = {}
    async for mode, payload in graph.astream(
        {"messages": messages}, config=config, stream_mode=["messages", "updates", "values"]
    ):
        if mode == "messages":
            chunk = payload[0] if isinstance(payload, tuple) else payload
            # 增量 chunk 的 type 为 "AIMessageChunk"（完整消息才是 "ai"）——实测
            if getattr(chunk, "type", "") not in ("ai", "AIMessageChunk"):
                continue
            # 工具参数生成阶段（大文件内容在 args 里，不走 text/thinking）——
            # 用户实测曾在此「卡住」数十秒无任何输出，发增量事件供宿主显示进度
            for tc in getattr(chunk, "tool_call_chunks", None) or []:
                frag = tc.get("args") if isinstance(tc, dict) else getattr(tc, "args", "")
                on_event(
                    {
                        "type": "tool_args",
                        "name": (tc.get("name") if isinstance(tc, dict) else "") or "",
                        "delta": len(frag or ""),
                    }
                )
            content = getattr(chunk, "content", "")
            if isinstance(content, str):
                if content:
                    on_event({"type": "token", "text": content})
                continue
            # Anthropic 风格 content blocks：text 段走 token，thinking 段独立事件
            for block in content if isinstance(content, list) else []:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "text" and block.get("text"):
                    on_event({"type": "token", "text": str(block["text"])})
                elif block.get("type") == "thinking" and block.get("thinking"):
                    on_event({"type": "thinking", "text": str(block["thinking"])})
        elif mode == "updates" and payload:
            emit_tool_events(payload, on_event)
        elif mode == "values" and isinstance(payload, dict):
            final = payload
    return final or await graph.ainvoke({"messages": messages}, config=config)


async def salvage_state(graph: Any, thread_id: str) -> list[Any]:
    """从检查点捞取半途消息（未修复的原始列表；无现场返回空列表）。"""
    try:
        snap = await graph.aget_state({"configurable": {"thread_id": thread_id}})
        return list((snap.values or {}).get("messages") or []) if snap else []
    except Exception:  # noqa: BLE001 — salvage 尽力而为，失败不掩盖原异常
        return []
