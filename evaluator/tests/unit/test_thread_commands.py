"""thread_commands（commands 形态）测试 — httpx.MockTransport 全离线。"""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from pydantic import ValidationError

from agent_eval.core.exceptions import AgentProtocolError
from agent_eval.execution.channels import thread_commands
from agent_eval.execution.channels.agent_protocol import AgentProtocolChannel
from agent_eval.execution.channels.thread_commands import (
    final_ai_text,
    messages_from_input,
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


def test_messages_from_input_str_wraps_user_message() -> None:
    msgs = messages_from_input("你好")
    assert len(msgs) == 1
    assert msgs[0]["role"] == "user"
    assert msgs[0]["content"] == "你好"
    assert msgs[0]["id"]


def test_messages_from_input_messages_dict_passthrough_with_defaults() -> None:
    msgs = messages_from_input({"messages": [{"role": "user", "content": "hi"}]})
    assert msgs[0]["content"] == "hi" and msgs[0]["id"]
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
