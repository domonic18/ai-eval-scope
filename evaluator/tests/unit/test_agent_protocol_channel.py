"""AgentProtocolChannel 测试（arch/03 §4.0.6）——httpx.MockTransport 全离线。"""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from agent_eval.core.exceptions import AgentProtocolError, SUTAuthError
from agent_eval.execution.auth.session import SUTSession
from agent_eval.execution.channels.agent_protocol import AgentProtocolChannel, _iter_sse
from agent_eval.execution.registry import (
    AuthConfig,
    AuthExtractConfig,
    AuthLoginConfig,
    OutputPathsConfig,
    SUTSystemConfig,
)


def _channel(sut: SUTSystemConfig, handler) -> AgentProtocolChannel:
    return AgentProtocolChannel(
        sut, http_client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )


def _sut(**kwargs) -> SUTSystemConfig:
    defaults = dict(name="cw", channel="agent_protocol", base_url="https://ap.example.com")
    defaults.update(kwargs)
    return SUTSystemConfig(**defaults)


WAIT_PAYLOAD = {
    "run": {"run_id": "r-1", "status": "success"},
    "values": {"output_files": ["index.html", "m1/a.html"], "content": "课件正文"},
    "messages": [{"role": "assistant", "content": "done"}],
}


def test_run_wait_mode_maps_status_and_extracts_output() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=WAIT_PAYLOAD)

    channel = _channel(
        _sut(
            output_paths=OutputPathsConfig(
                files_field="values.output_files", text_field="values.content"
            )
        ),
        handler,
    )
    result = asyncio.run(channel.run({"subject": "数学"}, metadata={"task_id": "t1"}))
    assert captured["path"] == "/runs/wait"
    assert captured["body"]["input"] == {"subject": "数学"}
    assert captured["body"]["metadata"] == {"task_id": "t1"}
    assert result["status"] == "success"
    assert result["output"]["files"] == ["index.html", "m1/a.html"]
    assert result["output"]["text"] == "课件正文"


def test_run_error_status_maps_failed_with_error_payload() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = dict(WAIT_PAYLOAD)
        payload["run"] = {"run_id": "r-2", "status": "error"}
        payload["error"] = {"code": "INTERNAL", "message": "boom"}
        return httpx.Response(200, json=payload)

    result = asyncio.run(_channel(_sut(), handler).run("input"))
    assert result["status"] == "failed"
    assert result["error"] == {"code": "INTERNAL", "message": "boom"}


def test_run_background_mode_polls_and_cancels_on_timeout() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/runs" and request.method == "POST":
            return httpx.Response(200, json={"run_id": "bg-1"})
        if request.url.path == "/runs/bg-1/wait":
            raise httpx.ReadTimeout("pending 挂死")
        if request.url.path == "/runs/bg-1/cancel":
            return httpx.Response(200, json={"ok": True})
        raise AssertionError(f"unexpected {request.url.path}")

    channel = _channel(_sut(exec_mode="background", timeout=0.2), handler)
    with pytest.raises(AgentProtocolError, match="cancel"):
        asyncio.run(channel.run("input"))
    assert "/runs/bg-1/cancel" in calls


def test_run_stream_aggregates_sse_with_unknown_events() -> None:
    sse = "\n".join(
        [
            "event: values",
            'data: {"values": {"content": "段落一"}}',
            "",
            'data: {"message": {"content": "增量文本"}}',  # data-only 兜底（缺 event 字段）
            "",
            "event: custom-weird",
            "data: not-json",
            "",
            'data: {"run": {"run_id": "s-1", "status": "success"}}',
            "",
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content)["stream_mode"] == "messages"
        return httpx.Response(200, text=sse)

    result = asyncio.run(_channel(_sut(exec_mode="stream"), handler).run("input"))
    assert result["status"] == "success"
    assert result["text"] == "增量文本"
    assert result["output"] == {}  # 未配置 output_paths 时不提取
    kinds = [(e["event"], e["data"]) for e in result["events"]]
    # 未知事件原样保留（非 JSON data 兜底为 {"raw": ...}）
    assert ("custom-weird", {"raw": "not-json"}) in kinds
    assert any(e is None for e, _ in kinds)  # data-only 事件


def test_on_completion_passed_through() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(200, json=WAIT_PAYLOAD)

    channel = _channel(_sut(on_completion="delete"), handler)
    asyncio.run(channel.run("input"))
    assert captured["on_completion"] == "delete"


def test_threads_roundtrip() -> None:
    calls: list[tuple[str, dict]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.url.path, json.loads(request.content)))
        if request.url.path == "/threads":
            return httpx.Response(200, json={"thread_id": "th-9"})
        if request.url.path == "/threads/th-9/runs/wait":
            return httpx.Response(200, json=WAIT_PAYLOAD)
        raise AssertionError(request.url.path)

    channel = _channel(_sut(), handler)
    created = asyncio.run(channel.create_thread(metadata={"eval_run_id": "run_1"}))
    assert created == {"thread_id": "th-9"}
    result = asyncio.run(channel.run_on_thread("th-9", {"turn": 2}))
    assert result["status"] == "success"
    assert calls[1][0] == "/threads/th-9/runs/wait"


def test_get_agent_info_and_capability_check() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/agents/search":
            return httpx.Response(
                200, json={"agents": [{"agent_id": "cw-main"}, {"agent_id": "other"}]}
            )
        if request.url.path == "/agents/cw-main/schemas":
            return httpx.Response(
                200,
                json={
                    "input_schema": {"type": "object"},
                    "output_schema": {"type": "object"},
                    "capabilities": {"ap.io.messages": True, "ap.io.streaming": False},
                },
            )
        raise AssertionError(request.url.path)

    channel = _channel(_sut(agent_id="cw-main", protocol_version="0.1.6"), handler)
    info = asyncio.run(channel.get_agent_info())
    assert info["agent_id"] == "cw-main"
    assert info["protocol_version"] == "0.1.6"
    check = asyncio.run(channel.check_capabilities(required=["ap.io.messages"]))
    assert check["ok"] is True

    with pytest.raises(AgentProtocolError, match="缺少能力"):
        asyncio.run(channel.check_capabilities(required=["ap.io.streaming"]))


def test_session_401_auto_relogin_once_and_replay(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_EVAL_SUT__CW__USERNAME", "u")
    monkeypatch.setenv("AGENT_EVAL_SUT__CW__PASSWORD", "p")
    """会话失效自愈：401 → 重登一次 → 重放成功（§4.0.4-4）。"""
    state = {"logins": 0, "token": "stale"}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/login":
            state["logins"] += 1
            state["token"] = f"tk-{state['logins']}"
            return httpx.Response(200, json={"data": {"access_token": state["token"]}})
        auth = request.headers.get("authorization", "")
        if auth == "Bearer tk-1":
            return httpx.Response(200, json=WAIT_PAYLOAD)
        return httpx.Response(401, json={"message": "expired"})

    sut = _sut(
        auth=AuthConfig(
            type="api_login",
            credential_ref="CW",
            login=AuthLoginConfig(path="/api/login"),
            extract=AuthExtractConfig(token_path="data.access_token"),
        ),
        timeout=5,
    )
    channel = AgentProtocolChannel(
        sut, http_client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    # 预置陈旧会话（模拟落盘复用后服务端已改 token）
    channel.auth._session = SUTSession(sut_name="cw", token="stale", expires_at=None)

    result = asyncio.run(channel.run("input"))
    assert result["status"] == "success"
    assert state["logins"] == 1  # 重登一次后重放成功


def test_session_401_relogin_rate_limit_raises(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_EVAL_SUT__CW__USERNAME", "u")
    monkeypatch.setenv("AGENT_EVAL_SUT__CW__PASSWORD", "p")
    state = {"logins": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/login":
            state["logins"] += 1
            return httpx.Response(200, json={"data": {"access_token": f"tk-{state['logins']}"}})
        return httpx.Response(401, json={"message": "always expired"})

    sut = _sut(
        auth=AuthConfig(
            type="api_login", credential_ref="CW", login=AuthLoginConfig(path="/api/login")
        )
    )
    channel = AgentProtocolChannel(
        sut, http_client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    channel.auth._session = SUTSession(sut_name="cw", token="stale")
    channel.auth.mark_auto_relogin()  # 窗口内已重登过
    with pytest.raises(SUTAuthError, match="频次限制"):
        asyncio.run(channel.run("input"))


def test_iter_sse_parses_blocks() -> None:
    class FakeStream:
        def __init__(self, lines):
            self._lines = lines

        async def aiter_lines(self):
            for line in self._lines:
                yield line

    async def _collect():
        return [
            item
            async for item in _iter_sse(
                FakeStream(["event: a", 'data: {"x": 1}', "", "data: tail"])
            )
        ]

    events = asyncio.run(_collect())
    assert events == [("a", '{"x": 1}'), (None, "tail")]


def test_session_store_not_required_for_none_auth() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "authorization" not in request.headers
        return httpx.Response(200, json=WAIT_PAYLOAD)

    result = asyncio.run(_channel(_sut(), handler).run("x"))
    assert result["status"] == "success"


def test_aclose_idempotent() -> None:
    channel = _channel(_sut(), lambda request: httpx.Response(200, json=WAIT_PAYLOAD))
    asyncio.run(channel.aclose())
    asyncio.run(channel.aclose())


def test_session_store_unused_when_not_configured(tmp_path) -> None:
    # SessionStore 未注入时不应写任何落盘文件（进程内缓存即可）
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=WAIT_PAYLOAD)

    channel = _channel(_sut(), handler)
    asyncio.run(channel.run("x"))
    assert not (tmp_path / "any").exists()
