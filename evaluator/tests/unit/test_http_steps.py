"""http_steps 测试——MockTransport 全离线。"""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from agent_eval.core.exceptions import SUTChannelError
from agent_eval.execution.channels import http_steps
from agent_eval.execution.channels.generic_http import GenericHttpChannel
from agent_eval.execution.registry import (
    PollConfig,
    RequestStepConfig,
    RequestTemplateConfig,
    SUTSystemConfig,
)


def _session_sut(**kwargs) -> SUTSystemConfig:
    """create(once) → send → history 链：M1 会话续接的标准形态。"""
    steps = [
        RequestStepConfig(
            name="create",
            method="POST",
            path="/chat/conversations",
            once=True,
            body={"student_id": None},
        ),
        RequestStepConfig(
            name="send",
            method="POST",
            path="/chat/conversations/{{ create.data.id }}/messages",
            body={"content": "{{ input }}"},
        ),
        RequestStepConfig(
            name="history", method="GET", path="/chat/conversations/{{ create.data.id }}"
        ),
    ]
    defaults = dict(
        name="http-sut",
        channel="generic_http",
        base_url="https://api.example.com",
        request_template=RequestTemplateConfig(steps=steps),
        response_mapping={"text": "data.messages.-1.content"},
    )
    defaults.update(kwargs)
    return SUTSystemConfig(**defaults)


def _channel(sut: SUTSystemConfig, handler) -> GenericHttpChannel:
    return GenericHttpChannel(
        sut, http_client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )


_HISTORY = {
    "data": {"messages": [{"role": "assistant", "content": "拒绝回复"}]},
}


def _conversation_handler(
    captured: list[httpx.Request], *, stale_ids: frozenset[str] = frozenset()
):
    """会话型 API 假件：POST /conversations 从 c1 起发号；
    stale_ids 内的会话一律 404（服务端会话过期形态）。"""
    counter = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        if request.url.path == "/chat/conversations" and request.method == "POST":
            counter["n"] += 1
            return httpx.Response(200, json={"data": {"id": f"c{counter['n']}"}})
        for seg in request.url.path.split("/"):
            if seg in stale_ids:
                return httpx.Response(404, text="conversation not found")
        if request.url.path.endswith("/messages"):
            return httpx.Response(200, json={"code": 0})
        return httpx.Response(200, json=_HISTORY)

    return handler


def _seed(channel: GenericHttpChannel, session_key: str, cid: str) -> None:
    """预置 once 缓存（等价「首轮已建会话」）。"""
    channel._session.cache_for(session_key)["create"] = {"data": {"id": cid}}  # noqa: SLF001


def test_once_step_executes_first_call_then_skips_second() -> None:
    """once 步首轮执行、次轮跳过——会话型 API 不再每轮重建会话。"""
    captured: list[httpx.Request] = []
    channel = _channel(_session_sut(), _conversation_handler(captured))

    first = asyncio.run(channel.run("第一轮", metadata={}, session_key="t1"))
    assert [r.url.path for r in captured] == [
        "/chat/conversations",
        "/chat/conversations/c1/messages",
        "/chat/conversations/c1",
    ]
    assert first["text"] == "拒绝回复"

    captured.clear()
    asyncio.run(channel.run("第二轮", metadata={}, session_key="t1"))
    # 次轮仅 send + history 两请求——create 命中缓存不重复
    assert [r.url.path for r in captured] == [
        "/chat/conversations/c1/messages",
        "/chat/conversations/c1",
    ]
    assert json.loads(captured[0].content) == {"content": "第二轮"}


def test_session_keys_are_isolated() -> None:
    """不同 session_key 互不可见——多任务隔离由键空间机械保证。"""
    captured: list[httpx.Request] = []
    channel = _channel(_session_sut(), _conversation_handler(captured))

    asyncio.run(channel.run("hi", metadata={}, session_key="t1"))
    asyncio.run(channel.run("hi", metadata={}, session_key="t2"))
    create_calls = [r for r in captured if r.url.path == "/chat/conversations"]
    assert len(create_calls) == 2  # 各自会话各建一次


def test_new_session_discards_cache_and_rebuilds() -> None:
    """new_session=True 丢弃当前键缓存整链重建（Agent 显式换会话的逃生口）。"""
    captured: list[httpx.Request] = []
    channel = _channel(_session_sut(), _conversation_handler(captured))

    asyncio.run(channel.run("hi", metadata={}, session_key="t1"))
    captured.clear()
    asyncio.run(channel.run("hi", metadata={}, session_key="t1", new_session=True))
    assert [r.url.path for r in captured][0] == "/chat/conversations"  # create 重新执行


def test_self_heal_rebuilds_on_stale_session_404() -> None:
    """非 once 步 404 且缓存非空 → 自动清缓存整链重建一次（服务端会话过期形态）。"""
    captured: list[httpx.Request] = []
    # c9 是「已过期」的旧会话；重建后拿到新会话 c1
    channel = _channel(_session_sut(), _conversation_handler(captured, stale_ids=frozenset({"c9"})))
    _seed(channel, "t1", "c9")

    result = asyncio.run(channel.run("hi", metadata={}, session_key="t1"))

    assert result["status"] == "success"
    assert result["session_rebuilt"] is True
    paths = [r.url.path for r in captured]
    assert paths[0] == "/chat/conversations/c9/messages"  # 首轮尝试用旧会话 → 404
    assert paths[1] == "/chat/conversations"  # 自愈重建 create
    assert "/chat/conversations/c1/messages" in paths  # 后续步用新会话


def test_self_heal_still_404_fails_with_both_rounds_evidence() -> None:
    """重建仍 404 → failed 带两轮证据，不无限重试。"""
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        if request.url.path == "/chat/conversations" and request.method == "POST":
            return httpx.Response(200, json={"data": {"id": "c1"}})  # 重建成功拿到新会话
        if request.url.path.endswith("/messages"):
            return httpx.Response(404, text="gone")  # 重建也救不了的业务性 404
        return httpx.Response(200, json=_HISTORY)

    channel = _channel(_session_sut(), handler)
    _seed(channel, "t1", "c9")
    result = asyncio.run(channel.run("hi", metadata={}, session_key="t1"))

    assert result["status"] == "failed"
    assert result["http_status"] == 404
    assert "会话自愈已整链重建一次仍 404" in result["error"]["message"]
    # 两轮证据：send 两轮各 404 一次 + create 重建一次（自愈仅触发一次）
    paths = [r.url.path for r in captured]
    assert paths == [
        "/chat/conversations/c9/messages",
        "/chat/conversations",
        "/chat/conversations/c1/messages",
    ]


def test_self_heal_not_triggered_on_first_call_404() -> None:
    """首轮（缓存空）非 once 步 404 是真实 API 错误——不自愈，直接 failed。"""
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        if request.url.path.endswith("/messages"):
            return httpx.Response(404, text="nope")
        return httpx.Response(200, json={"data": {"id": "c1"}})

    channel = _channel(_session_sut(), handler)
    result = asyncio.run(channel.run("hi", metadata={}, session_key="t1"))
    assert result["status"] == "failed"
    assert "session_rebuilt" not in result
    assert len([r for r in captured if r.url.path == "/chat/conversations"]) == 1


def test_lru_evicted_session_self_heals_via_full_rebuild() -> None:
    """LRU 淘汰即丢会话——再次使用时缓存为空，整链重建兜底（语义自洽）。"""
    captured: list[httpx.Request] = []
    channel = _channel(_session_sut(), _conversation_handler(captured))
    channel._session = http_steps.StepSession(max_sessions=1)  # noqa: SLF001 — 压缩容量验证淘汰

    asyncio.run(channel.run("hi", metadata={}, session_key="a"))
    asyncio.run(channel.run("hi", metadata={}, session_key="b"))  # 淘汰 a 的缓存
    captured.clear()
    asyncio.run(channel.run("hi", metadata={}, session_key="a"))
    # a 的会话已被淘汰 → create 重新执行（整链重建），而非引用已失效的缓存
    assert [r.url.path for r in captured][0] == "/chat/conversations"


def test_poll_until_true_passes_without_sleep() -> None:
    """poll do-while：until 渲染为真即通过（首轮为真不 sleep）。"""
    intervals: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        intervals.append(seconds)

    steps = [
        RequestStepConfig(
            name="status",
            method="GET",
            path="/jobs/1",
            poll=PollConfig(until="{{ status.data.state == 'succeeded' }}", interval_s=0.01),
        )
    ]
    sut = SUTSystemConfig(
        name="job-api",
        channel="generic_http",
        base_url="https://api.example.com",
        request_template=RequestTemplateConfig(steps=steps),
        response_mapping={"text": "data.result"},
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": {"state": "succeeded", "result": "产物"}})

    original_sleep = http_steps._sleep
    http_steps._sleep = fake_sleep
    try:
        result = asyncio.run(_channel(sut, handler).run("hi", metadata={}))
    finally:
        http_steps._sleep = original_sleep

    assert result["status"] == "success"
    assert result["text"] == "产物"
    assert intervals == []  # 首轮即终态，未进入等待


def test_poll_retries_until_terminal_with_injected_sleep() -> None:
    """前几轮未终态 → 注入 sleep 推进，终态轮通过（不等真实间隔）。"""
    intervals: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        intervals.append(seconds)

    steps = [
        RequestStepConfig(
            name="status",
            method="GET",
            path="/jobs/1",
            poll=PollConfig(until="{{ status.data.state == 'succeeded' }}", interval_s=3.0),
        )
    ]
    sut = SUTSystemConfig(
        name="job-api",
        channel="generic_http",
        base_url="https://api.example.com",
        request_template=RequestTemplateConfig(steps=steps),
        response_mapping={"text": "data.result"},
    )
    states = iter(["running", "running", "succeeded"])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": {"state": next(states), "result": "产物"}})

    original_sleep = http_steps._sleep
    http_steps._sleep = fake_sleep
    try:
        result = asyncio.run(_channel(sut, handler).run("hi", metadata={}))
    finally:
        http_steps._sleep = original_sleep

    assert result["text"] == "产物"
    assert intervals == [3.0, 3.0]  # 两轮未终态各等一个 interval


def test_poll_server_errors_do_not_abort_polling() -> None:
    """轮询中 ≥400 不立即失败（受理后短暂不一致是常态），续轮直至终态。"""
    polls = {"n": 0}

    async def fake_sleep(seconds: float) -> None:
        pass

    steps = [
        RequestStepConfig(
            name="status",
            method="GET",
            path="/jobs/1",
            poll=PollConfig(until="{{ status.data.state == 'done' }}", timeout_s=5.0),
        )
    ]
    sut = SUTSystemConfig(
        name="job-api",
        channel="generic_http",
        base_url="https://api.example.com",
        request_template=RequestTemplateConfig(steps=steps),
        response_mapping={"text": "data.result"},
    )

    def handler(request: httpx.Request) -> httpx.Response:
        polls["n"] += 1
        if polls["n"] == 1:
            return httpx.Response(503, text="temporarily unavailable")
        return httpx.Response(200, json={"data": {"state": "done", "result": "产物"}})

    original_sleep = http_steps._sleep
    http_steps._sleep = fake_sleep
    try:
        result = asyncio.run(_channel(sut, handler).run("hi", metadata={}))
    finally:
        http_steps._sleep = original_sleep

    assert result["status"] == "success"
    assert result["text"] == "产物"
    assert polls["n"] == 2


def test_poll_timeout_raises_with_evidence() -> None:
    """超时整体失败（SUTChannelError），错误含尝试次数与最后响应摘录。"""
    polls = {"n": 0}

    async def fake_sleep(seconds: float) -> None:
        pass

    steps = [
        RequestStepConfig(
            name="status",
            method="GET",
            path="/jobs/1",
            poll=PollConfig(until="{{ status.data.state == 'done' }}", timeout_s=0.05),
        )
    ]
    sut = SUTSystemConfig(
        name="job-api",
        channel="generic_http",
        base_url="https://api.example.com",
        request_template=RequestTemplateConfig(steps=steps),
        response_mapping={"text": "data.result"},
    )

    def handler(request: httpx.Request) -> httpx.Response:
        polls["n"] += 1
        return httpx.Response(200, json={"data": {"state": f"running-{polls['n']}"}})

    original_sleep = http_steps._sleep
    http_steps._sleep = fake_sleep
    try:
        with pytest.raises(SUTChannelError, match="轮询超时") as exc_info:
            asyncio.run(_channel(sut, handler).run("hi", metadata={}))
    finally:
        http_steps._sleep = original_sleep

    message = str(exc_info.value)
    assert "尝试" in message
    assert "running-" in message  # 最后响应摘录入证
    assert polls["n"] >= 2  # do-while：至少两次尝试


def test_poll_until_undefined_variable_fails_loud() -> None:
    """until 引用未声明变量 → StrictUndefined 渲染报错（fail-loud 不静默空转）。"""
    steps = [
        RequestStepConfig(
            name="status",
            method="GET",
            path="/jobs/1",
            poll=PollConfig(until="{{ stat.data.state == 'done' }}"),  # 拼错步骤名
        )
    ]
    sut = SUTSystemConfig(
        name="job-api",
        channel="generic_http",
        base_url="https://api.example.com",
        request_template=RequestTemplateConfig(steps=steps),
        response_mapping={},
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": {"state": "done"}})

    with pytest.raises(SUTChannelError, match="渲染失败"):
        asyncio.run(_channel(sut, handler).run("hi", metadata={}))


def test_poll_self_reference_visible_in_until() -> None:
    """until 自引用本步响应（capture 先于终态判定进入上下文）。"""
    steps = [
        RequestStepConfig(
            name="status",
            method="GET",
            path="/jobs/1",
            poll=PollConfig(until="{{ status.data.ok }}"),
        )
    ]
    sut = SUTSystemConfig(
        name="job-api",
        channel="generic_http",
        base_url="https://api.example.com",
        request_template=RequestTemplateConfig(steps=steps),
        response_mapping={"text": "data.result"},
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": {"ok": "yes", "result": "产物"}})

    result = asyncio.run(_channel(sut, handler).run("hi", metadata={}))
    assert result["status"] == "success"
    assert result["text"] == "产物"
