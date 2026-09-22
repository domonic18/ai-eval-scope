"""Agent Protocol commands 形态 SSE 流式 run（thread_commands 拆出）。

run.start + SSE /stream(/events) 订阅，终态一律以 state 轮询收口（流只是
提前收口的优化）。与 run/poll 编排（thread_commands）分离：两形态各自的
传输路径独立成模块，共用信封、请求头与 state 收口。
"""

from __future__ import annotations

import json
import time
import uuid
from typing import TYPE_CHECKING, Any

from agent_eval.core.exceptions import AgentProtocolError
from agent_eval.execution.channels.sse import iter_sse
from agent_eval.execution.channels.thread_commands import (
    _poll_state,
    conversation_headers,
    finalize_run_result,
    run_start_envelope,
)

if TYPE_CHECKING:  # 仅类型标注；运行时依赖经 thread_commands 单向引用
    from agent_eval.execution.channels.agent_protocol import AgentProtocolChannel

SSE_DEADLINE_EXTRA_S = 5.0  # SSE 总时长上限 = sut.timeout + 余量（超时后仍由 state 轮询收口）
# lifecycle 终态提示（最终状态一律以 GET state 为准，这里仅提前结束 SSE 等待）
TERMINAL_LIFECYCLE_EVENTS = frozenset(
    {"done", "completed", "complete", "error", "idle", "finished", "cancelled"}
)


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
        json_body=run_start_envelope(
            input, configurable=channel.sut.configurable, metadata=metadata
        ),
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
                # SSE 总时长上限：SUT 等待用户输入（反问暂停）时服务端可能持续发
                # keepalive 心跳，read timeout 永不触发——deadline 在行级判定（注释帧
                # 不产生事件，事件级检查形同虚设），超时跳出后仍由 _poll_state 按状态
                # 收口（真相源是 state，流只是提前收口的优化）
                sse_deadline = time.monotonic() + channel.sut.timeout + SSE_DEADLINE_EXTRA_S
                async for event_name, data_text in iter_sse(stream_response, sse_deadline):
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
    values, pending = await _poll_state(
        channel, tid, 0, interrupt_types=channel.sut.interrupt_types
    )
    return finalize_run_result(
        channel,
        run_id=None,
        thread_id=tid,
        values=values,
        pending=pending,
        events=events,
        terminal_event_seen=terminal_seen,
    )
