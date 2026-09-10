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
SSE_DEADLINE_EXTRA_S = 5.0  # SSE 总时长上限 = sut.timeout + 余量（超时后仍由 state 轮询收口）
AI_ROLES = frozenset({"ai", "assistant"})
COMPACT_TEXT_MAX_CHARS = 800  # 消息摘要单条文本上限（整表仍受 bounded_result 截断约束）
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
    本地构造值必须显式标注（local-simulated）：执行 Agent 曾把该「成功」当
    服务端健康证据，在 commands 端点 404 后反复重试不撒手。
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
        "source": "local-simulated",
        "note": (
            "能力描述由本地配置构造（commands 形态无 /agents/search 端点）——"
            "本次未访问服务器，不能作为服务端可达的证据"
        ),
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


def pending_ask_questions(state: dict[str, Any] | None) -> list[dict[str, Any]]:
    """提取 state 中挂起的 ask_question 中断（LangGraph interrupt 结构）。

    结构（2026-09 对 sasan/DeepAgents 实测）：state.next 非空（如 ['tools']），
    state.tasks[].interrupts[] 携带 {"id", "value": {"type": "ask_question",
    "questions": [{"question", "options": [{"value", "description"}], "multiple"?}]}}；
    顶层 state.interrupts 作兼容提取。此前提取缺失——反问被当普通未终态轮询到
    「run 超时」（300s），反问永远到不了评估 Agent。
    """
    if not isinstance(state, dict):
        return []
    interrupts: list[Any] = []
    for task in state.get("tasks") or []:
        if isinstance(task, dict):
            interrupts.extend(task.get("interrupts") or [])
    if isinstance(state.get("interrupts"), list):
        interrupts.extend(state["interrupts"])
    questions: list[dict[str, Any]] = []
    for interrupt in interrupts:
        if not isinstance(interrupt, dict):
            continue
        value = interrupt.get("value")
        if not isinstance(value, dict) or value.get("type") != "ask_question":
            continue
        for question in value.get("questions") or []:
            if isinstance(question, dict):
                questions.append({**question, "interrupt_id": interrupt.get("id") or ""})
    return questions


def ask_question_tool_call_ids(messages: list[dict[str, Any]] | None) -> list[str]:
    """从消息流提取 ask_question 工具调用 id（input.respond 的 response 键）。

    中断恢复契约（2026-09 对 sasan 实测）：input.respond 的 params.response 以
    {ask_question 工具调用 id: [逐题答案]} 键值对提交，而工具调用 id 只存在于
    消息流（ai 消息的 tool_calls），interrupt value 不携带。
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


def respond_input_envelope(
    interrupt_id: str, response: dict[str, Any], *, command_id: int = 2
) -> dict[str, Any]:
    """构造 input.respond 命令信封（应答 ask_question 中断，续跑挂起的 run）。

    namespace 恒为 []（SUT 前端序列化器同款）；response 形如
    {ask_question 工具调用 id: [{"selected": ["选项值"], ...}]}——直接下发新
    消息会被 PENDING_QUESTION 拒绝，unknown 的 method 名均报 unknown_command
    （run.resume / question.answer 等 8 个候选名 2026-09 实测排除）。
    """
    return {
        "id": command_id,
        "method": "input.respond",
        "params": {"namespace": [], "interrupt_id": interrupt_id, "response": response},
    }


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
    run_id = (payload.get("result") or {}).get("run_id")
    values, pending = await _poll_state(channel, tid, baseline)
    return finalize_run_result(
        channel, run_id=run_id, thread_id=tid, values=values, pending=pending
    )


def finalize_run_result(
    channel: AgentProtocolChannel,
    *,
    run_id: str | None,
    thread_id: str,
    values: dict[str, Any],
    pending: list[dict[str, Any]],
    **extra: Any,
) -> dict[str, Any]:
    """由终态 values 组装 run 结果：success 走 output 提取；interrupted 附结构化反问。"""
    messages = values.get("messages") or []
    text = final_ai_text(messages)
    result: dict[str, Any] = {
        "status": "interrupted" if pending else "success",
        "run": {"run_id": run_id, "thread_id": thread_id},
        "values": values,
        "messages": messages,
        "output": channel._extract_output(values) or ({"text": text} if text else {}),
        "text": text,
        **extra,
    }
    if pending:
        result["questions"] = pending
    return result


def run_start_envelope(
    input: Any,
    *,
    configurable: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """构造 run.start 命令信封；消息置于 params.input.messages（v4.6.4 契约）。

    执行器与协议探测共用同一构造（v3.9 同构：probe 说执行器的方言，
    信封/消息形态/请求头永不漂移）。
    """
    params: dict[str, Any] = {"input": {"messages": messages_from_input(input)}}
    if configurable:
        params["config"] = {"configurable": dict(configurable)}
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
    channel: AgentProtocolChannel,
    thread_id: str,
    baseline: int,
    *,
    resolved_interrupt: str | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """轮询 state 至终态；遇 ask_question 反问挂起即提前返回，不再空转超时。

    Returns:
        (values, pending_questions)。pending 非空 = run 挂起等应答
        （interrupt 挂载，next 通常非空），调用方按 interrupted 语义收口。

    Args:
        resolved_interrupt: 刚应答过的中断 id——input.respond 提交后存在竞态
            窗口（应答已受理、图未推进），旧中断仍挂在 state 上，跳过它继续等
            真正的推进/终态，否则会把同一反问再次当挂起返回。
    """
    deadline = time.monotonic() + channel.sut.timeout
    last_values: dict[str, Any] = {}
    while True:
        state = await _get_state(channel, thread_id)
        if state is not None:
            last_values = state.get("values") or {}
            messages = last_values.get("messages") or []
            pending = [
                q
                for q in pending_ask_questions(state)
                if q.get("interrupt_id") != resolved_interrupt
            ]
            if pending:
                return last_values, pending
            finished = not (state.get("next") or [])
            if finished and len(messages) > baseline and final_ai_text(messages):
                return last_values, []
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
                async for event_name, data_text in _iter_sse(stream_response, sse_deadline):
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
    values, pending = await _poll_state(channel, tid, 0)
    return finalize_run_result(
        channel,
        run_id=None,
        thread_id=tid,
        values=values,
        pending=pending,
        events=events,
        terminal_event_seen=terminal_seen,
    )


class SSEDeadlineError(Exception):
    """SSE 行级 deadline 超限：keepalive 心跳喂住连接，read timeout 永不触发。

    SUT 等待用户输入（反问暂停）时服务端可持续发注释帧——行级 deadline 是唯一
    可靠上限。commands 形态捕获后转 state 轮询收口（真相源）；runs 形态无兜底，
    直接失败。
    """


async def _iter_sse(
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
