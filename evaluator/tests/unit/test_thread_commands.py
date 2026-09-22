"""thread_commands（commands 形态）测试 — httpx.MockTransport 全离线。"""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from pydantic import ValidationError

from agent_eval.core.exceptions import AgentProtocolError, AgentProtocolTimeoutError
from agent_eval.execution.channels import commands_stream, thread_commands
from agent_eval.execution.channels.agent_protocol import AgentProtocolChannel
from agent_eval.execution.channels.interrupts import (
    ask_question_tool_call_ids,
    pending_ask_questions,
    unrecognized_interrupt_types,
)
from agent_eval.execution.channels.message_digest import (
    compact_messages,
    final_ai_text,
    has_ai_message_from,
)
from agent_eval.execution.channels.thread_commands import (
    messages_from_input,
    respond_input_envelope,
)
from agent_eval.execution.registry import AuthConfig, SUTSystemConfig


def _sut(**kwargs) -> SUTSystemConfig:
    defaults = dict(
        name="tcw",
        channel="agent_protocol",
        base_url="https://tcw.example.com",
        protocol_flavor="commands",
    )
    defaults.update(kwargs)
    return SUTSystemConfig(**defaults)


def _channel(sut: SUTSystemConfig, handler) -> AgentProtocolChannel:
    return AgentProtocolChannel(
        sut, http_client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )


# ─── 纯函数 ───


def test_messages_from_input_str_wraps_human_message() -> None:
    msgs = messages_from_input("你好")
    assert len(msgs) == 1
    assert msgs[0]["type"] == "human"
    assert msgs[0]["content"] == "你好"
    assert msgs[0]["id"]


def test_messages_from_input_messages_dict_passthrough_with_defaults() -> None:
    msgs = messages_from_input({"messages": [{"content": "hi"}]})
    assert msgs[0]["type"] == "human" and msgs[0]["content"] == "hi" and msgs[0]["id"]
    assert messages_from_input({"messages": ["裸文本"]})[0]["content"] == "裸文本"


def test_messages_from_input_plain_dict_serializes_to_json() -> None:
    msgs = messages_from_input({"subject": "数学"})
    assert json.loads(msgs[0]["content"]) == {"subject": "数学"}


def test_messages_from_input_unsupported_type_raises() -> None:
    with pytest.raises(AgentProtocolError, match="不支持的 run 输入类型"):
        messages_from_input(["列表不支持"])


def test_final_ai_text_typed_blocks_skip_reasoning() -> None:
    messages = [
        {
            "role": "ai",
            "content": [
                {"type": "reasoning", "reasoning": "内心独白"},
                {"type": "text", "text": "对外回答"},
            ],
        }
    ]
    assert final_ai_text(messages) == "对外回答"


def test_final_ai_text_takes_last_nonempty_and_string_content() -> None:
    messages = [
        {"role": "ai", "content": "第一条"},
        {"role": "ai", "content": [{"type": "text", "text": ""}]},
        {"role": "ai", "content": "最终回答"},
    ]
    assert final_ai_text(messages) == "最终回答"
    assert final_ai_text([{"role": "human", "content": "用户"}]) == ""


def test_has_ai_message_from_checks_only_messages_after_start() -> None:
    """终态判定谓词：baseline 之后出现过 ai 消息即算，内容形态不限。"""
    messages = [
        {"role": "human", "content": "旧问题"},
        {"role": "ai", "content": "旧回答"},
        {"type": "human", "content": "新问题"},
        {
            "type": "ai",
            "content": [
                {"type": "reasoning", "reasoning": "先编写课件文件"},
                {"type": "tool_call", "name": "write_file", "args": {}},
            ],
        },
    ]
    assert has_ai_message_from(messages, 2)  # 新增 ai 无 text 块也算（工具调用收尾形态）
    assert not has_ai_message_from(messages, 4)  # 越界起点
    assert not has_ai_message_from(messages[:3], 3)  # 空切片
    assert has_ai_message_from(None, 0) is False


# ─── commands_run（经 AgentProtocolChannel.run 分发） ───


def test_channel_run_dispatches_commands_flavor_with_conversation_header() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            captured["path"] = request.url.path
            captured["auth"] = request.headers.get("Authorization")
            captured["conv"] = request.headers.get("makers-conversation-id")
            captured["body"] = json.loads(request.content)
            return httpx.Response(200, json={"type": "success", "result": {"run_id": "run-9"}})
        if request.url.path.endswith("/state"):
            return httpx.Response(
                200,
                json={
                    "next": [],
                    "values": {
                        "messages": [
                            {"role": "human", "content": "只回复两个字"},
                            {"role": "ai", "content": [{"type": "text", "text": "收到"}]},
                        ]
                    },
                },
            )
        raise AssertionError(f"unexpected {request.method} {request.url.path}")

    import os

    os.environ["AGENT_EVAL_SUT__TCW__TOKEN"] = "tk-1"
    sut = _sut(
        configurable={"modelId": "19"},
        auth=AuthConfig(type="static_token", credential_ref="TCW"),
    )
    result = asyncio.run(_channel(sut, handler).run("只回复两个字", metadata={"task_id": "t1"}))
    assert captured["path"].startswith("/threads/") and captured["path"].endswith("/commands")
    assert captured["auth"] == "Bearer tk-1"
    assert captured["conv"] and captured["conv"] in captured["path"]
    assert captured["body"]["method"] == "run.start"
    assert captured["body"]["params"]["config"]["configurable"] == {"modelId": "19"}
    assert captured["body"]["params"]["metadata"] == {"task_id": "t1"}
    # 消息置于 params.input.messages 且为 LangGraph type 格式
    sent = captured["body"]["params"]["input"]["messages"]
    assert sent == [{"type": "human", "id": sent[0]["id"], "content": "只回复两个字"}]
    assert result["status"] == "success"
    assert result["run"]["run_id"] == "run-9" and result["run"]["thread_id"] == captured["conv"]
    assert result["text"] == "收到"
    assert result["output"]["text"] == "收到"


def test_channel_run_commands_error_envelope_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(
                200, json={"type": "error", "error": "必须指定模型(modelId)", "code": "E1"}
            )
        raise AssertionError("不应触发 state 轮询")

    with pytest.raises(AgentProtocolError, match="必须指定模型"):
        asyncio.run(_channel(_sut(), handler).run("hi"))


def test_run_on_thread_waits_for_new_ai_reply_beyond_baseline() -> None:
    """多轮：既有终态线程上，须等新 ai 回复才算完成（防误读上一轮）。"""
    started = {"done": False}
    old_state = {
        "next": [],
        "values": {
            "messages": [
                {"role": "human", "content": "旧问题"},
                {"role": "ai", "content": "旧回答"},
            ]
        },
    }
    new_state = {
        "next": [],
        "values": {
            "messages": [
                *old_state["values"]["messages"],
                {"role": "human", "content": "新问题"},
                {"role": "ai", "content": [{"type": "text", "text": "新回答"}]},
            ]
        },
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            started["done"] = True
            return httpx.Response(200, json={"type": "success", "result": {"run_id": "r2"}})
        return httpx.Response(200, json=new_state if started["done"] else old_state)

    channel = _channel(_sut(), handler)
    result = asyncio.run(channel.run_on_thread("00000000-0000-0000-0000-000000000001", "新问题"))
    assert result["text"] == "新回答"
    assert result["run"]["thread_id"] == "00000000-0000-0000-0000-000000000001"


def test_poll_state_timeout_raises_with_partial_detail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(thread_commands, "COMMANDS_POLL_INTERVAL_S", 0.01)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json={"type": "success", "result": {"run_id": "r3"}})
        return httpx.Response(200, json={"next": ["agent"], "values": {"messages": []}})

    channel = _channel(_sut(timeout=0.1), handler)
    with pytest.raises(AgentProtocolError, match="run 超时"):
        asyncio.run(channel.run("hi"))


def test_poll_state_accepts_tool_call_ending_turn_without_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """修 2026-09-11 误报超时事故：SUT 写完产物即结束（ai 尾随为工具调用块、
    无 text 块），终态判定不再要求尾随文本——工具调用收尾照常收口。"""
    monkeypatch.setattr(thread_commands, "COMMANDS_POLL_INTERVAL_S", 0.01)
    completed = {
        "next": [],
        "values": {
            "messages": [
                {"type": "human", "id": "m1", "content": "生成课件"},
                {
                    "type": "ai",
                    "id": "m2",
                    "content": [
                        {"type": "reasoning", "reasoning": "先编写课件文件"},
                        {
                            "type": "tool_call",
                            "name": "write_file",
                            "args": {"path": "课件.html"},
                        },
                    ],
                },
                {"type": "tool", "id": "m3", "content": "written"},
            ]
        },
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json={"type": "success", "result": {"run_id": "r6"}})
        return httpx.Response(200, json=completed)

    channel = _channel(_sut(timeout=1.0), handler)  # 不修此缺陷时必然烧满超时报「run 超时」
    result = asyncio.run(channel.run("生成课件"))
    assert result["status"] == "success"
    assert result["text"] == ""  # 尾随文本降级为内容信号，为空不阻塞终态
    assert result["values"]["messages"][2]["type"] == "tool"  # values 照常透出（产物证据）


def test_poll_state_timeout_reports_thread_idle(monkeypatch: pytest.MonkeyPatch) -> None:
    """超时诊断：thread_idle=true = SUT 已空闲但终态未收口（契约/判定问题）；
    同时锁定基线后无 ai 消息不构成终态（防起跑窗口误收口）。"""
    monkeypatch.setattr(thread_commands, "COMMANDS_POLL_INTERVAL_S", 0.01)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json={"type": "success", "result": {"run_id": "r7"}})
        return httpx.Response(
            200, json={"next": [], "values": {"messages": [{"type": "human", "content": "hi"}]}}
        )

    channel = _channel(_sut(timeout=0.1), handler)
    with pytest.raises(AgentProtocolError, match="run 超时") as exc_info:
        asyncio.run(channel.run("hi"))
    # 机械守卫按类型拦截（isinstance），不做错误文案字符串匹配
    assert isinstance(exc_info.value, AgentProtocolTimeoutError)
    assert exc_info.value.details.get("thread_idle") is True


def test_poll_state_stable_window_ignores_blank_window_misfire(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """settle 稳定窗（run 20260912_000410）：阶段切换的 next 瞬时空窗不再被
    单采样误判终态——空窗 → busy → 真终态×2 才收口，text 取终稿非中间播报。"""
    monkeypatch.setattr(thread_commands, "COMMANDS_POLL_INTERVAL_S", 0.01)
    intermediate = [
        {"type": "human", "id": "m1", "content": "生成课件"},
        {"type": "ai", "id": "m2", "content": [{"type": "text", "text": "正在导出为 PDF"}]},
    ]
    gets = {"n": 0}

    def state_for(n: int) -> dict:
        if n == 1:  # 空窗：生成→导出阶段切换，next 瞬时为空（旧代码在此误判终态）
            return {"next": [], "values": {"messages": intermediate}}
        if n == 2:  # 导出阶段实际开工
            return {"next": ["agent"], "values": {"messages": intermediate}}
        final = [*intermediate, {"type": "ai", "id": "m3", "content": "课件已生成完毕"}]
        return {"next": [], "values": {"messages": final}}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json={"type": "success", "result": {"run_id": "r-s"}})
        gets["n"] += 1
        return httpx.Response(200, json=state_for(gets["n"]))

    channel = _channel(_sut(timeout=1.0), handler)
    result = asyncio.run(channel.run("生成课件"))
    assert result["status"] == "success"
    assert result["text"] == "课件已生成完毕"  # 非中间播报
    assert gets["n"] == 4  # 空窗(1) + busy 归零(2) + 真终态重数(3,4)


def test_poll_state_timeout_when_terminal_never_stabilizes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """空窗反复出现终态条件永不连满稳定窗 → 按超时收口；最后一次采样空闲
    但稳定未满，thread_idle=true 诊断语义不降级。"""
    monkeypatch.setattr(thread_commands, "COMMANDS_POLL_INTERVAL_S", 0.5)  # > timeout
    gets = {"n": 0}
    blank = {
        "next": [],
        "values": {
            "messages": [
                {"type": "human", "id": "m1", "content": "hi"},
                {"type": "ai", "id": "m2", "content": "半成品播报"},
            ]
        },
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json={"type": "success", "result": {"run_id": "r-u"}})
        gets["n"] += 1
        if gets["n"] == 1:
            return httpx.Response(200, json={"next": ["agent"], "values": blank["values"]})
        return httpx.Response(200, json=blank)  # 之后恒空闲，但永远只连续 1 次

    channel = _channel(_sut(timeout=0.1), handler)
    with pytest.raises(AgentProtocolError, match="run 超时") as exc_info:
        asyncio.run(channel.run("hi"))
    assert isinstance(exc_info.value, AgentProtocolTimeoutError)
    assert exc_info.value.details.get("thread_idle") is True
    assert gets["n"] == 2


def test_commands_stream_collects_events_and_finalizes_by_state() -> None:
    sse = "\n".join(
        [
            'data: {"type":"event","seq":1,"method":"lifecycle","params":{"data":{"event":"running"}}}',
            "",
            'data: {"type":"event","seq":2,"method":"values","params":{"data":{"foo":1}}}',
            "",
            'data: {"type":"event","seq":3,"method":"lifecycle","params":{"data":{"event":"done"}}}',
            "",
        ]
    )
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(f"{request.method} {request.url.path}")
        if request.method == "POST":
            return httpx.Response(200, json={"type": "success", "result": {"run_id": "rs"}})
        if "/stream/events" in request.url.path:
            return httpx.Response(200, text=sse, headers={"Content-Type": "text/event-stream"})
        if request.url.path.endswith("/state"):
            return httpx.Response(
                200,
                json={"next": [], "values": {"messages": [{"role": "ai", "content": "流式完成"}]}},
            )
        raise AssertionError(f"unexpected {request.url.path}")

    channel = _channel(_sut(exec_mode="stream"), handler)
    result = asyncio.run(channel.run("hi"))
    assert result["status"] == "success" and result["text"] == "流式完成"
    assert result["terminal_event_seen"] is True
    assert [e["data"]["method"] for e in result["events"]] == ["lifecycle", "values", "lifecycle"]
    assert any(p.endswith("/stream/events") for p in calls)


def test_commands_stream_deadline_breaks_endless_keepalive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SUT 反问暂停 + keepalive 注释帧喂住连接：SSE 无终态也必须在 deadline 跳出。

    注释帧不产生 SSE 事件——deadline 必须行级判定（事件级检查永不执行，
    2026-09 卡死事故回归）。跳出后终态与文本由 state 轮询收口。
    """
    monkeypatch.setattr(thread_commands, "COMMANDS_POLL_INTERVAL_S", 0.01)
    # SSE_DEADLINE_EXTRA_S 由 commands_stream 模块消费，patch 其定义处
    monkeypatch.setattr(commands_stream, "SSE_DEADLINE_EXTRA_S", 0.0)

    async def endless_keepalive():
        while True:
            yield b": keepalive\n\n"
            await asyncio.sleep(0.02)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json={"type": "success", "result": {"run_id": "rk"}})
        if "/stream" in request.url.path:
            return httpx.Response(
                200, content=endless_keepalive(), headers={"Content-Type": "text/event-stream"}
            )
        if request.url.path.endswith("/state"):
            return httpx.Response(
                200,
                json={
                    "next": [],
                    "values": {"messages": [{"role": "ai", "content": "请选择课件类型"}]},
                },
            )
        raise AssertionError(f"unexpected {request.url.path}")

    channel = _channel(_sut(exec_mode="stream", timeout=0.2), handler)
    result = asyncio.run(channel.run("hi"))
    assert result["status"] == "success" and result["text"] == "请选择课件类型"
    assert result["terminal_event_seen"] is False  # SSE 未经终态收口，由 state 兜底


def test_create_thread_commands_flavor_is_local_uuid() -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover — 不应发请求
        raise AssertionError("commands 形态建线程不发网络请求")

    thread = asyncio.run(_channel(_sut(), handler).create_thread())
    assert len(thread["thread_id"]) == 36  # UUID 形态


def test_get_agent_info_commands_flavor_is_local_descriptor() -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover — 不应发请求
        raise AssertionError("commands 形态能力自描述不发网络请求")

    info = asyncio.run(_channel(_sut(), handler).get_agent_info())
    assert info["protocol_flavor"] == "commands"
    assert info["agent_id"] == "default"
    assert info["endpoints"]["commands"] == "/threads/{thread_id}/commands"


# ─── registry / auth 新字段 ───


def test_registry_rejects_unknown_protocol_flavor() -> None:
    with pytest.raises(ValidationError, match="protocol_flavor"):
        SUTSystemConfig(
            name="bad",
            channel="agent_protocol",
            base_url="https://x.example.com",
            protocol_flavor="telepathy",
        )


def test_registry_defaults_flavor_runs_and_configurable_dict() -> None:
    sut = SUTSystemConfig(name="ok", channel="agent_protocol", base_url="https://x.example.com")
    assert sut.protocol_flavor == "runs"
    assert sut.configurable == {}


# ─── askQuestion 中断与恢复（反问不再空转超时，input.respond 续跑） ───

INTERRUPT_ID = "8dfca77c1c85056d7243d0067a6d8ba3"
ASK_TOOL_CALL_ID = "ask_question_0_f0a8bb6e"


def _interrupt_state() -> dict:
    """复刻 2026-09 sasan 实测挂起形态：next 非空 + tasks[].interrupts 携带反问。"""
    return {
        "next": ["tools"],
        "tasks": [
            {
                "interrupts": [
                    {
                        "id": INTERRUPT_ID,
                        "value": {
                            "type": "ask_question",
                            "questions": [
                                {
                                    "question": "课件的交付形式是哪种？",
                                    "options": [
                                        {"value": "ppt", "description": "演示文稿"},
                                        {"value": "word", "description": "文档"},
                                    ],
                                }
                            ],
                        },
                    }
                ]
            }
        ],
        "values": {
            "messages": [
                {"type": "human", "id": "m1", "content": "请生成《春》的课件"},
                {
                    "type": "ai",
                    "id": "m2",
                    "content": [{"type": "text", "text": "请选择课件交付形式"}],
                    "tool_calls": [
                        {
                            "name": "ask_question",
                            "id": ASK_TOOL_CALL_ID,
                            "args": {"questions": ["课件的交付形式是哪种？"]},
                        }
                    ],
                },
            ]
        },
    }


def test_pending_ask_questions_extracts_from_tasks_and_top_level() -> None:
    state = _interrupt_state()
    questions = pending_ask_questions(state)
    assert len(questions) == 1
    assert questions[0]["question"] == "课件的交付形式是哪种？"
    assert questions[0]["options"][0]["value"] == "ppt"
    assert questions[0]["interrupt_id"] == INTERRUPT_ID
    # 顶层 interrupts 兼容 + 非反问中断/空 state 均不误报
    top_level = {"interrupts": state["tasks"][0]["interrupts"]}
    assert pending_ask_questions(top_level)[0]["interrupt_id"] == INTERRUPT_ID
    assert (
        pending_ask_questions({"tasks": [{"interrupts": [{"id": "x", "value": {"type": "hint"}}]}]})
        == []
    )
    assert pending_ask_questions(None) == []


def test_pending_ask_questions_honors_configured_interrupt_types() -> None:
    """识别集可配：非 ask_question 形态的 SUT 中断按 sut.interrupt_types 识别。"""
    state = {
        "tasks": [
            {
                "interrupts": [
                    {
                        "id": "int-9",
                        "value": {
                            "type": "select_option",
                            "questions": [{"question": "选择交付格式", "options": []}],
                        },
                    }
                ]
            }
        ]
    }
    # 缺省集不识别（sasan 契约≠协议标准）；显式配置后识别
    assert pending_ask_questions(state) == []
    questions = pending_ask_questions(state, interrupt_types=["ask_question", "select_option"])
    assert len(questions) == 1
    assert questions[0]["interrupt_id"] == "int-9"


def test_unrecognized_interrupt_types_lists_unknown_sorted() -> None:
    """超时诊断：线程上挂着的未配置中断类型按序透出，识别集内的不算。"""
    state = {
        "tasks": [
            {
                "interrupts": [
                    {"id": "a", "value": {"type": "approval"}},
                    {"id": "b", "value": {"type": "ask_question"}},
                    {"id": "c", "value": {"type": "budget_confirm"}},
                ]
            }
        ]
    }
    assert unrecognized_interrupt_types(state) == ["approval", "budget_confirm"]
    assert unrecognized_interrupt_types(state, interrupt_types=["ask_question", "approval"]) == [
        "budget_confirm"
    ]
    assert unrecognized_interrupt_types(None) == []


def test_poll_state_timeout_reports_unrecognized_interrupts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """「run 超时」的真因可见：错误 details 透出未识别中断类型。"""
    monkeypatch.setattr(thread_commands, "COMMANDS_POLL_INTERVAL_S", 0.01)
    stuck_state = {
        "next": ["tools"],
        "tasks": [{"interrupts": [{"id": "i-1", "value": {"type": "human_approval"}}]}],
        "values": {"messages": []},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json={"type": "success", "result": {"run_id": "r4"}})
        return httpx.Response(200, json=stuck_state)

    channel = _channel(_sut(timeout=0.1), handler)
    with pytest.raises(AgentProtocolError, match="run 超时") as exc_info:
        asyncio.run(channel.run("hi"))
    assert exc_info.value.details.get("unrecognized_interrupts") == ["human_approval"]


def test_run_interrupted_by_configured_custom_interrupt(monkeypatch: pytest.MonkeyPatch) -> None:
    """接入新 SUT：interrupt_types 配置扩展后，自定义中断按 interrupted 收口。"""
    monkeypatch.setattr(thread_commands, "COMMANDS_POLL_INTERVAL_S", 0.01)
    custom_state = {
        "next": ["tools"],
        "tasks": [
            {
                "interrupts": [
                    {
                        "id": "int-7",
                        "value": {
                            "type": "select_option",
                            "questions": [{"question": "输出格式?", "options": [{"value": "pdf"}]}],
                        },
                    }
                ]
            }
        ],
        "values": {"messages": []},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json={"type": "success", "result": {"run_id": "r5"}})
        return httpx.Response(200, json=custom_state)

    sut = _sut(timeout=1.0, interrupt_types=["select_option"])
    channel = _channel(sut, handler)
    result = asyncio.run(channel.run("生成报告"))
    assert result["status"] == "interrupted"
    assert result["questions"][0]["question"] == "输出格式?"
    assert result["questions"][0]["interrupt_id"] == "int-7"


def test_ask_question_tool_call_ids_from_tool_calls_and_content_blocks() -> None:
    messages = _interrupt_state()["values"]["messages"]
    assert ask_question_tool_call_ids(messages) == [ASK_TOOL_CALL_ID]
    blocked = [{"content": [{"type": "tool_call", "name": "ask_question", "id": "askq-b"}]}]
    assert ask_question_tool_call_ids(blocked) == ["askq-b"]
    assert ask_question_tool_call_ids([{"tool_calls": [{"name": "other_tool", "id": "x"}]}]) == []


def test_respond_input_envelope_shape() -> None:
    response = {"answers": [{"selected": ["ppt"]}]}  # 前端 AskQuestionCard 同款
    envelope = respond_input_envelope(INTERRUPT_ID, response)
    assert envelope["method"] == "input.respond"
    assert envelope["params"]["namespace"] == []
    assert envelope["params"]["interrupt_id"] == INTERRUPT_ID
    assert envelope["params"]["response"] == response


def test_compact_messages_drops_reasoning_keeps_text_and_tool_calls() -> None:
    """reasoning 块丢弃 + 文本/工具调用骨架保留——修 6 万字符推理挤占截断窗口。"""
    messages = [
        {"type": "human", "id": "m1", "content": "请生成《春》的课件"},
        {
            "type": "ai",
            "id": "m2",
            "content": [
                {"type": "reasoning", "reasoning": "R" * 60000},
                {"type": "text", "text": "x" * 100 + "请选择课件交付形式"},
            ],
            "tool_calls": [
                {"name": "ask_question", "id": ASK_TOOL_CALL_ID, "args": {"questions": ["q"]}}
            ],
        },
        {"type": "tool", "tool_call_id": ASK_TOOL_CALL_ID, "content": "工具观测" * 2000},
    ]
    dumped = json.dumps(compact_messages(messages), ensure_ascii=False)
    assert "R" * 10 not in dumped  # reasoning 丢弃
    assert "请选择课件交付形式" in dumped  # 尾部语义不被头部体量挤占
    assert ASK_TOOL_CALL_ID in dumped  # 工具调用 id 保留（诊断留档）
    compact = compact_messages(messages)
    assert all(len(m.get("content", "")) <= 800 for m in compact)  # 超长文本逐条封顶


def test_run_interrupted_by_ask_question_returns_questions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """反问挂起 → 提前返回 interrupted + 结构化 questions，不再空转到超时。"""
    monkeypatch.setattr(thread_commands, "COMMANDS_POLL_INTERVAL_S", 0.01)
    gets = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json={"type": "success", "result": {"run_id": "r-i"}})
        gets["n"] += 1
        return httpx.Response(200, json=_interrupt_state())

    channel = _channel(_sut(timeout=0.3), handler)  # 不修此缺陷时必然 raise「run 超时」
    result = asyncio.run(channel.run("请生成《春》的课件"))
    assert result["status"] == "interrupted"
    assert result["questions"][0]["question"] == "课件的交付形式是哪种？"
    assert result["questions"][0]["interrupt_id"] == INTERRUPT_ID
    assert result["text"] == "请选择课件交付形式"
    assert gets["n"] == 1  # 首次轮询即识别挂起，无空转


def test_answer_interrupt_resumes_run_and_skips_stale_interrupt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """input.respond 信封契约 + 应答受理/图推进竞态窗口内跳过旧中断。"""
    monkeypatch.setattr(thread_commands, "COMMANDS_POLL_INTERVAL_S", 0.01)
    captured: dict = {}
    gets = {"n": 0}
    resumed_state = {
        "next": [],
        "values": {
            "messages": [
                *_interrupt_state()["values"]["messages"],
                {"type": "ai", "id": "m3", "content": [{"type": "text", "text": "课件已生成"}]},
            ]
        },
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            captured["body"] = json.loads(request.content)
            captured["conv"] = request.headers.get("makers-conversation-id")
            return httpx.Response(200, json={"type": "success", "result": {"run_id": "r-r"}})
        gets["n"] += 1
        if gets["n"] == 3:  # 应答已受理但图未推进——旧中断仍在 state 上
            return httpx.Response(200, json=_interrupt_state())
        if gets["n"] >= 4:
            return httpx.Response(200, json=resumed_state)
        return httpx.Response(200, json=_interrupt_state())  # GET#1 应答前基线

    channel = _channel(_sut(timeout=1.0), handler)
    response = {"answers": [{"selected": ["ppt"]}]}  # 前端 AskQuestionCard 同款
    result = asyncio.run(
        channel.answer_interrupt(
            "00000000-0000-0000-0000-000000000009",
            INTERRUPT_ID,
            response,
        )
    )
    assert result["status"] == "success" and result["text"] == "课件已生成"
    assert captured["conv"] == "00000000-0000-0000-0000-000000000009"
    envelope = captured["body"]
    assert envelope["method"] == "input.respond"
    assert envelope["params"]["interrupt_id"] == INTERRUPT_ID
    assert envelope["params"]["namespace"] == []
    assert envelope["params"]["response"] == response
    assert gets["n"] >= 4  # 旧中断被跳过，续轮询到真终态


def test_answer_interrupt_rejects_runs_flavor() -> None:
    """runs 形态无 input.respond——显式拒绝（预留，不静默乱发请求）。"""
    channel = _channel(_sut(protocol_flavor="runs"), lambda request: httpx.Response(200, json={}))
    with pytest.raises(AgentProtocolError, match="不支持中断应答"):
        asyncio.run(channel.answer_interrupt("t", INTERRUPT_ID, {}))


def test_cancel_run_tolerates_empty_body() -> None:
    """cancel 2xx 空体/非 JSON 不炸（staging 实测返回空体）；4xx 仍抛错。"""
    channel = _channel(
        _sut(), lambda request: httpx.Response(200, text="", headers={"content-length": "0"})
    )
    result = asyncio.run(channel.cancel_run("run-1", "interrupt"))
    assert result["run_id"] == "run-1"
    assert result["action"] == "interrupt"

    def reject(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    channel2 = _channel(_sut(), reject)
    with pytest.raises(AgentProtocolError):
        asyncio.run(channel2.cancel_run("run-1", "interrupt"))


def test_commands_stream_interrupted_reports_questions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """stream 形态同样收口 interrupted 反问（SSE 终态后 state 轮询识别挂起）。"""
    sse = 'data: {"type":"event","seq":1,"method":"lifecycle","params":{"data":{"event":"idle"}}}'
    monkeypatch.setattr(thread_commands, "COMMANDS_POLL_INTERVAL_S", 0.01)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json={"type": "success", "result": {"run_id": "rs"}})
        if "/stream" in request.url.path:
            return httpx.Response(200, text=sse, headers={"Content-Type": "text/event-stream"})
        return httpx.Response(200, json=_interrupt_state())

    channel = _channel(_sut(exec_mode="stream", timeout=1.0), handler)
    result = asyncio.run(channel.run("hi"))
    assert result["status"] == "interrupted"
    assert result["questions"][0]["interrupt_id"] == INTERRUPT_ID
