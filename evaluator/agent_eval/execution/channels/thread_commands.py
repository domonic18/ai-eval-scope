"""Agent Protocol commands 形态传输（官方 Streaming 端点，arch/03 §4.0.6）。

对应部署形态（AG-UI 网关族）：POST /threads/{id}/commands（JSON-RPC 风格
信封，method=run.start）+ GET /threads/{id}/state 轮询。线程由客户端生成
UUID（首个 run.start 隐式建线程）；业务请求携带 `makers-conversation-id`
头作网关路由约定。

本模块只保留 run/poll 编排与线契约（信封/消息/请求头）；消息摘要见
message_digest.py、中断提取见 interrupts.py、SSE 解析见 sse.py、流式
run 见 commands_stream.py（plan/07 G4 拆分）。
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from agent_eval.core.exceptions import AgentProtocolError, AgentProtocolTimeoutError
from agent_eval.execution.channels.interrupts import (
    pending_ask_questions,
    unrecognized_interrupt_types,
)
from agent_eval.execution.channels.message_digest import final_ai_text, has_ai_message_from

if TYPE_CHECKING:  # 防循环导入（agent_protocol 反向引用本模块的函数）
    from agent_eval.execution.channels.agent_protocol import AgentProtocolChannel

COMMANDS_POLL_INTERVAL_S = 1.5


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
    # run_on_thread 语境：记录既有消息数，终态判定要求"新增 ai 消息"防误读上一轮；
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
    values, pending = await _poll_state(
        channel, tid, baseline, interrupt_types=channel.sut.interrupt_types
    )
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


def respond_input_envelope(
    interrupt_id: str, response: dict[str, Any], *, command_id: int = 2
) -> dict[str, Any]:
    """构造 input.respond 命令信封（应答 ask_question 中断，续跑挂起的 run）。

    namespace 恒为 []（SUT 前端序列化器同款）；response 为前端 AskQuestionCard
    同款 ``{"answers": [{"selected": ["选项值"], ...}, ...]}``（顶层 answers 键，
    不按工具调用 id 键控——2026-09-11 实测勘误，旧记载致 SUT 端「答案数据无效」）。
    直接下发新消息会被 PENDING_QUESTION 拒绝，unknown 的 method 名均报
    unknown_command（run.resume / question.answer 等 8 个候选名 2026-09 实测排除）。
    """
    return {
        "id": command_id,
        "method": "input.respond",
        "params": {"namespace": [], "interrupt_id": interrupt_id, "response": response},
    }


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
    interrupt_types: Sequence[str] = ("ask_question",),
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """轮询 state 至终态；遇反问挂起（interrupt_types 识别集内）即提前返回。

    终态 = next 为空且 baseline 之后新增过 ai 消息（内容形态不限）——不以
    「尾随 ai 文本」为条件，以工具调用收尾的 SUT 不再被误判超时
    （2026-09-11 实测事故：课件写完即结束、无结束语，空转烧满 900s）。

    Returns:
        (values, pending_questions)。pending 非空 = run 挂起等应答
        （interrupt 挂载，next 通常非空），调用方按 interrupted 语义收口。

    Args:
        resolved_interrupt: 刚应答过的中断 id——input.respond 提交后存在竞态
            窗口（应答已受理、图未推进），旧中断仍挂在 state 上，跳过它继续等
            真正的推进/终态，否则会把同一反问再次当挂起返回。
        interrupt_types: 反问挂起识别集（sut.interrupt_types）。
    """
    deadline = time.monotonic() + channel.sut.timeout
    last_values: dict[str, Any] = {}
    unrecognized: set[str] = set()
    while True:
        state = await _get_state(channel, thread_id)
        if state is not None:
            last_values = state.get("values") or {}
            messages = last_values.get("messages") or []
            pending = [
                q
                for q in pending_ask_questions(state, interrupt_types)
                if q.get("interrupt_id") != resolved_interrupt
            ]
            if pending:
                return last_values, pending
            unrecognized.update(unrecognized_interrupt_types(state, interrupt_types))
            finished = not (state.get("next") or [])
            if finished and has_ai_message_from(messages, baseline):
                return last_values, []
        if time.monotonic() >= deadline:
            details: dict[str, Any] = {
                "sut": channel.sut.name,
                "thread_id": thread_id,
                "messages": len(last_values.get("messages") or []),
                # 超时时线程是否已空闲：true = SUT 已完成但终态判定未接受
                # （判定逻辑缺陷），false = SUT 真未跑完（生成慢或卡死）
                "thread_idle": state is not None and not (state.get("next") or []),
            }
            if unrecognized:
                # 线程挂有未配置识别的中断形态——「超时」的真因大概率是它，
                # 补进 sut.interrupt_types 即可识别（plan/07 G2）
                details["unrecognized_interrupts"] = sorted(unrecognized)
            raise AgentProtocolTimeoutError(
                f"run 超时：state 轮询 {channel.sut.timeout}s 未达终态",
                details=details,
            )
        await asyncio.sleep(COMMANDS_POLL_INTERVAL_S)
