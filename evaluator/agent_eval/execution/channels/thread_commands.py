"""Agent Protocol commands 形态传输（官方 Streaming 端点，arch/03 §4.0.6）。

对应部署形态（AG-UI 网关族）：POST /threads/{id}/commands（JSON-RPC 风格
信封，method=run.start）+ GET /threads/{id}/state 轮询 + SSE
/threads/{id}/stream(/events)。线程由客户端生成 UUID（首个 run.start
隐式建线程）；业务请求携带 `makers-conversation-id` 头作网关路由约定。
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

from agent_eval.core.exceptions import AgentProtocolError

if TYPE_CHECKING:  # 防循环导入（agent_protocol 反向引用本模块的函数）
    from agent_eval.execution.channels.agent_protocol import AgentProtocolChannel

COMMANDS_POLL_INTERVAL_S = 1.5
AI_ROLES = frozenset({"ai", "assistant"})
# lifecycle 终态提示（最终状态一律以 GET state 为准，这里仅提前结束 SSE 等待）
TERMINAL_LIFECYCLE_EVENTS = frozenset(
    {"done", "completed", "complete", "error", "idle", "finished", "cancelled"}
)


def conversation_headers(thread_id: str) -> dict[str, str]:
    """AG-UI 网关要求的会话路由头。"""
    return {"makers-conversation-id": thread_id}


def commands_agent_info(
    channel: AgentProtocolChannel, agent_id: str | None = None
) -> dict[str, Any]:
    """commands 形态能力描述（本地构造）。

    /agents/search 是 runs 形态端点；AG-UI 网关族对未知路径回 SPA HTML，
    探测只会得到非 JSON，故 commands 形态以配置自描述替代网络发现。
    """
    resolved = agent_id or channel.sut.agent_id or "default"
    return {
        "agent_id": resolved,
        "agents": [resolved],
        "schemas": {},
        "protocol_version": channel.sut.protocol_version,
        "protocol_flavor": "commands",
        "endpoints": {
            "commands": "/threads/{thread_id}/commands",
            "state": "/threads/{thread_id}/state",
            "stream": "/threads/{thread_id}/stream(/events)",
        },
    }


def messages_from_input(input: Any) -> list[dict[str, Any]]:
    """str → 单条 human 消息；{messages:[...]} → 补 type/id 透传；其他 dict → JSON 串。

    消息形态为 LangGraph/LangChain 格式（`type: human|ai`，无 role 字段）——
    AG-UI 网关族按 type 识别，Agent Protocol 的 `role: user` 会被静默丢弃
    （v4.6.4 实测：SUT 收不到输入、按空会话即兴回答）。
    """
    if isinstance(input, str):
        return [{"type": "human", "id": str(uuid.uuid4()), "content": input}]
    if isinstance(input, dict) and isinstance(input.get("messages"), list):
        out: list[dict[str, Any]] = []
        for message in input["messages"]:
            if isinstance(message, str):
                message = {"content": message}
            msg = dict(message) if isinstance(message, dict) else {"content": message}
            msg.setdefault("type", "human")
            msg.setdefault("id", str(uuid.uuid4()))
            out.append(msg)
        return out
    if isinstance(input, dict):
        return [
            {
                "type": "human",
                "id": str(uuid.uuid4()),
                "content": json.dumps(input, ensure_ascii=False),
            }
        ]
    raise AgentProtocolError(f"不支持的 run 输入类型: {type(input).__name__}")


def final_ai_text(messages: list[dict[str, Any]] | None) -> str:
    """取最后一条含非空文本的 ai 消息（content 为类型块列表，跳过 reasoning）。"""
    for message in reversed(messages or []):
        if message.get("role") not in AI_ROLES and message.get("type") not in AI_ROLES:
            continue
        content = message.get("content")
        parts: list[str] = []
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(block.get("text") or "")
        texts = [p for p in parts if p.strip()]
        if texts:
            return "\n".join(texts)
    return ""


# ─── run（commands + state 轮询；exec_mode=wait 语义） ───


async def commands_run(
    channel: AgentProtocolChannel,
    input: Any,
    *,
    thread_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """run.start + state 轮询至终态；fresh thread 客户端生成 UUID。"""
    tid = thread_id or str(uuid.uuid4())
    # run_on_thread 语境：记录既有消息数，终态判定要求"新增 ai 回复"防误读上一轮；
    # fresh thread 线程尚未创建，预取只会得到 404，baseline 直接为 0
    baseline = 0
    if thread_id:
        prior = await _get_state(channel, tid)
        baseline = len((prior or {}).get("values", {}).get("messages") or [])
    response = await channel.request(
        "POST",
        f"/threads/{tid}/commands",
        json_body=run_start_envelope(channel, input, metadata),
        headers=conversation_headers(tid),
    )
    payload = channel._json(response)
    if response.status_code >= 400 or payload.get("type") == "error" or "error" in payload:
        raise AgentProtocolError(
            f"run.start 失败: {payload.get('error')}",
            details={"sut": channel.sut.name, "thread_id": tid, "body": str(payload)[:500]},
        )
    run_id = (payload.get("result") or {}).get("run_id")
    values = await _poll_state(channel, tid, baseline)
    messages = values.get("messages") or []
    text = final_ai_text(messages)
    return {
        "status": "success",
        "run": {"run_id": run_id, "thread_id": tid},
        "values": values,
        "messages": messages,
        "output": channel._extract_output(values) or ({"text": text} if text else {}),
        "text": text,
    }


def run_start_envelope(
    channel: AgentProtocolChannel, input: Any, metadata: dict[str, Any] | None
) -> dict[str, Any]:
    """构造 run.start 命令信封；消息置于 params.input.messages（v4.6.4 契约）。"""
    params: dict[str, Any] = {"input": {"messages": messages_from_input(input)}}
    if channel.sut.configurable:
        params["config"] = {"configurable": dict(channel.sut.configurable)}
    if metadata:
        params["metadata"] = metadata
    return {"id": 1, "method": "run.start", "params": params}


async def _get_state(channel: AgentProtocolChannel, thread_id: str) -> dict[str, Any] | None:
    """GET state；线程尚未创建（404）返回 None。"""
    response = await channel.request(
        "GET", f"/threads/{thread_id}/state", headers=conversation_headers(thread_id)
    )
    if response.status_code == 404:
        return None
    return channel._json(response)


async def _poll_state(
    channel: AgentProtocolChannel, thread_id: str, baseline: int
) -> dict[str, Any]:
    """轮询 state 至终态：next==[] 且新增消息末尾为 ai 文本（未起跑/终态误读均不通过）。"""
    deadline = time.monotonic() + channel.sut.timeout
    last_values: dict[str, Any] = {}
    while True:
        state = await _get_state(channel, thread_id)
        if state is not None:
            last_values = state.get("values") or {}
            messages = last_values.get("messages") or []
            finished = not (state.get("next") or [])
            if finished and len(messages) > baseline and final_ai_text(messages):
                return last_values
        if time.monotonic() >= deadline:
            raise AgentProtocolError(
                f"run 超时：state 轮询 {channel.sut.timeout}s 未达终态",
                details={
                    "sut": channel.sut.name,
                    "thread_id": thread_id,
                    "messages": len(last_values.get("messages") or []),
                },
            )
        await asyncio.sleep(COMMANDS_POLL_INTERVAL_S)


# ─── run_stream（run.start + SSE /stream(/events) + 终态以 state 收口） ───


async def commands_stream(
    channel: AgentProtocolChannel,
    input: Any,
    *,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """SSE 流式收集事件；流端点差异（/stream vs /stream/events）自动回退。"""
    tid = str(uuid.uuid4())
    session = await channel.auth.get_session()
    base = channel.sut.base_url.rstrip("/")
    stream_headers = {
        **session.mount_headers(),
        **conversation_headers(tid),
        "Accept": "text/event-stream",
    }
    events: list[dict[str, Any]] = []
    terminal_seen = False
    # 先 run.start（流连接对尚未存在的线程可能 404，故先建线程再订阅）
    response = await channel.request(
        "POST",
        f"/threads/{tid}/commands",
        json_body=run_start_envelope(channel, input, metadata),
        headers=conversation_headers(tid),
    )
    payload = channel._json(response)
    if response.status_code >= 400 or payload.get("type") == "error" or "error" in payload:
        raise AgentProtocolError(
            f"run.start 失败: {payload.get('error')}",
            details={"sut": channel.sut.name, "thread_id": tid, "body": str(payload)[:500]},
        )
    for path in (f"/threads/{tid}/stream/events", f"/threads/{tid}/stream"):
        try:
            async with channel.client.stream(
                "GET", f"{base}{path}", headers=stream_headers, timeout=channel.sut.timeout
            ) as stream_response:
                if stream_response.status_code >= 400:
                    continue  # 换下一个候选路径
                async for event_name, data_text in _iter_sse(stream_response):
                    try:
                        data: Any = json.loads(data_text) if data_text else {}
                    except json.JSONDecodeError:
                        data = {"raw": data_text}
                    events.append({"event": event_name, "data": data})
                    method = data.get("method") if isinstance(data, dict) else None
                    event = (
                        data.get("params", {}).get("data", {}).get("event")
                        if isinstance(data, dict)
                        else None
                    )
                    if method == "lifecycle" and event in TERMINAL_LIFECYCLE_EVENTS:
                        terminal_seen = True
                        break
                break  # 成功连上即停止尝试候选路径
        except Exception:  # noqa: BLE001 — SSE 中断不致命，终态以 state 收口
            break
    # 无论 SSE 是否收齐，终态与文本一律以 state 为准
    values = await _poll_state(channel, tid, 0)
    messages = values.get("messages") or []
    text = final_ai_text(messages)
    return {
        "status": "success",
        "run": {"thread_id": tid},
        "values": values,
        "messages": messages,
        "output": {"text": text} if text else {},
        "text": text,
        "events": events,
        "terminal_event_seen": terminal_seen,
    }


async def _iter_sse(response: Any) -> AsyncIterator[tuple[str | None, str]]:
    """逐块解析 SSE：event:/data: 行组块；缺 id/event 字段按 data-only 兜底。"""
    event_name: str | None = None
    data_lines: list[str] = []

    async for line in response.aiter_lines():
        if line == "":
            if data_lines or event_name is not None:
                yield event_name, "\n".join(data_lines)
            event_name, data_lines = None, []
        elif line.startswith("event:"):
            event_name = line.split(":", 1)[1].strip()
        elif line.startswith("data:"):
            data_lines.append(line.split(":", 1)[1].strip())
        # id:/注释等未知行忽略（data-only 兜底）
    if data_lines or event_name is not None:
        yield event_name, "\n".join(data_lines)
