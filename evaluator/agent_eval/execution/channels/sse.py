"""SSE 行级解析（thread_commands 拆出，plan/07 G4）——runs 与 commands 两形态共用。

只负责「字节流 → (event, data) 块」的解析与 deadline 判定；事件语义、终态
收口归各传输模块（thread_commands / agent_protocol）。
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from typing import Any

from agent_eval.core.exceptions import AgentEvalError


class SSEDeadlineError(AgentEvalError):
    """SSE 行级 deadline 超限：keepalive 心跳喂住连接，read timeout 永不触发。

    SUT 等待用户输入（反问暂停）时服务端可持续发注释帧——行级 deadline 是唯一
    可靠上限。commands 形态捕获后转 state 轮询收口（真相源）；runs 形态无兜底，
    直接失败。
    """


async def iter_sse(
    response: Any, deadline: float | None = None
) -> AsyncIterator[tuple[str | None, str]]:
    """逐块解析 SSE：event:/data: 行组块；缺 id/event 字段按 data-only 兜底。

    deadline（monotonic 时刻）超限即抛 SSEDeadlineError（注释帧不产生事件，
    事件级检查形同虚设，必须在行级判定）。
    """
    event_name: str | None = None
    data_lines: list[str] = []

    async for line in response.aiter_lines():
        if deadline is not None and time.monotonic() >= deadline:
            raise SSEDeadlineError
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
