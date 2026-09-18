"""GenericHttpChannel 测试（arch/03 §4.2）——httpx.MockTransport 全离线。"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest

from agent_eval.agent.executor.http_tools import GenericHttpToolServer
from agent_eval.core.exceptions import SUTChannelError
from agent_eval.execution.channels.base import create_channel
from agent_eval.execution.channels.generic_http import GenericHttpChannel
from agent_eval.execution.registry import (
    RequestStepConfig,
    RequestTemplateConfig,
    SUTSystemConfig,
)


def _sut(**kwargs) -> SUTSystemConfig:
    defaults = dict(
        name="http-sut",
        channel="generic_http",
        base_url="https://api.example.com",
        request_template=RequestTemplateConfig(
            method="POST",
            path="/chat",
            headers={"X-Trace": "{{ metadata.task_id }}"},
            body={"query": "{{ input }}"},
        ),
        response_mapping={"text": "data.answer", "files": "data.files"},
    )
    defaults.update(kwargs)
    return SUTSystemConfig(**defaults)


def _channel(sut: SUTSystemConfig, handler) -> GenericHttpChannel:
    return GenericHttpChannel(
        sut, http_client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )


RESPONSE = {"data": {"answer": "课件正文", "files": ["a.md"]}}


def test_run_renders_template_and_extracts_mapping() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=RESPONSE)

    channel = _channel(_sut(), handler)
    result = asyncio.run(channel.run("帮我生成课件", metadata={"task_id": "t1"}))
    assert captured["path"] == "/chat"
    assert captured["body"] == {"query": "帮我生成课件"}
    assert captured["headers"]["x-trace"] == "t1"
    assert result["status"] == "success"
    assert result["text"] == "课件正文"
    assert result["output"] == {"text": "课件正文", "files": ["a.md"]}
    assert result["http_status"] == 200


def test_run_text_path_miss_maps_failed_with_excerpt() -> None:
    """text 已配置但路径未命中 → failed（不再静默兜底整包——假成功红线，v4.8）。"""
    sut = _sut(response_mapping={"text": "data.answer"})

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": "shape"})

    result = asyncio.run(_channel(sut, handler).run("hi", metadata={"task_id": "t0"}))
    assert result["status"] == "failed"
    assert result["error"]["code"] == "text_path_miss"
    assert "unexpected" in result["error"]["message"]  # 摘录供 Agent 自我修正映射
    assert result["output"] == {"text": "", "files": []}


def test_run_without_mapping_returns_plain_text_body() -> None:
    """纯文本 API（未配置 response_mapping）：整个响应体即回答，不被 JSON 解析拦住。"""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="纯文本回答")

    sut = _sut(response_mapping={})
    result = asyncio.run(_channel(sut, handler).run("hi", metadata={"task_id": "t0"}))
    assert result["status"] == "success"
    assert result["text"] == "纯文本回答"


def test_run_strict_undefined_raises_on_unknown_variable() -> None:
    """拼错变量名报错而非静默空串（静默会把「模板写错」伪装成「服务端返回空」）。"""
    sut = _sut(
        request_template=RequestTemplateConfig(
            method="POST", path="/chat", body={"q": "{{ inpoot }}"}
        )
    )

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover — 不应到达
        return httpx.Response(200, json={})

    with pytest.raises(SUTChannelError, match="渲染失败"):
        asyncio.run(_channel(sut, handler).run("hi", metadata={"task_id": "t0"}))


def test_run_str_body_rendered_then_json_loaded() -> None:
    sut = _sut(
        request_template=RequestTemplateConfig(
            method="POST", path="/chat", body='{"q": "{{ input }}"}'
        )
    )
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=RESPONSE)

    result = asyncio.run(_channel(sut, handler).run("hi", metadata={"task_id": "t0"}))
    assert captured["body"] == {"q": "hi"}
    assert result["status"] == "success"


def test_run_http_error_maps_failed_with_body_message() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    result = asyncio.run(_channel(_sut(), handler).run("hi", metadata={"task_id": "t0"}))
    assert result["status"] == "failed"
    assert result["error"]["code"] == "http_500"
    assert "boom" in result["error"]["message"]


def test_run_success_false_maps_failed() -> None:
    sut = _sut(response_mapping={"text": "data.answer", "success": "data.ok"})

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": {"answer": "x", "ok": False}})

    result = asyncio.run(_channel(sut, handler).run("hi", metadata={"task_id": "t0"}))
    assert result["status"] == "failed"
    assert result["error"]["code"] == "success_false"


def test_run_files_missing_path_raises() -> None:
    """files 为显式声明路径——未命中属配置变形，报错而非兜底。"""
    sut = _sut(response_mapping={"text": "data.answer", "files": "nope.files"})

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=RESPONSE)

    with pytest.raises(SUTChannelError, match="files 路径无法解析"):
        asyncio.run(_channel(sut, handler).run("hi", metadata={"task_id": "t0"}))


def test_channel_requires_request_template() -> None:
    with pytest.raises(SUTChannelError, match="request_template"):
        GenericHttpChannel(_sut(request_template=None))


def test_create_channel_builds_generic_http() -> None:
    channel = create_channel(_sut())
    assert isinstance(channel, GenericHttpChannel)
    assert channel.channel_type == "generic_http"


def test_health_check_static_template_validation() -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover — 不应发请求
        raise AssertionError("health_check 不应发网络请求")

    ok = asyncio.run(_channel(_sut(), handler).health_check())
    assert ok == {"status": "ok", "channel": "generic_http", "sut": "http-sut"}


def test_health_check_rejects_bad_template_syntax() -> None:
    sut = _sut(
        request_template=RequestTemplateConfig(method="POST", path="/chat/{% if %}", body=None)
    )

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover — 不应发请求
        raise AssertionError("health_check 不应发网络请求")

    with pytest.raises(SUTChannelError, match="path 模板语法错误"):
        asyncio.run(_channel(sut, handler).health_check())


# ── GenericHttpToolServer：sut_request 语义工具（与 agent_run 同约定） ────────


def _permissive_ledger() -> Any:
    """宽裕额度账本：成功路径测试的注入件（账本未注入=fail-closed 拒绝）。"""
    from agent_eval.agent.executor.ledger import ResourceLedger
    from agent_eval.execution.models import InteractionPolicy

    return ResourceLedger(InteractionPolicy(sut_calls_total=8, dispatch=4, nudges=2))


def test_sut_request_uninjected_ledger_fails_closed() -> None:
    """账本未注入即拒绝（fail-closed）：无账本不能等于无额度——装配遗漏时
    闸门收紧而非静默放行成无限额调用口（AI 审查硬化项）。拒绝在触网之前。"""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover — 不应到达
        calls["n"] += 1
        return httpx.Response(200, json=RESPONSE)

    server = GenericHttpToolServer(_channel(_sut(), handler))
    result = asyncio.run(server.sut_request("hi"))
    assert result["status"] == "failed"
    assert result["error"]["type"] == "BudgetExhausted"
    assert result["error"]["budget"] == "ledger_missing"
    assert "write_package" in result["error"]["guidance"]
    assert calls["n"] == 0  # 拒绝在触网之前


def test_sut_request_returns_result_and_records_last_run() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=RESPONSE)

    server = GenericHttpToolServer(_channel(_sut(), handler), default_metadata={"task_id": "t0"})
    server.ledger = _permissive_ledger()
    result = asyncio.run(server.sut_request("帮我生成课件"))
    assert result["status"] == "success"
    assert result["text"] == "课件正文"
    # input 随 last_run 记录：ExecutionAgent 机械回显守卫的判定信号源
    assert server.last_run == {
        "status": "success",
        "run_id": None,
        "text": "课件正文",
        "input": "帮我生成课件",
        "output": {"files": ["a.md"], "text": "课件正文"},  # 合同一：结构化交付入账
    }


def test_sut_request_merges_default_and_call_metadata() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["headers"] = dict(request.headers)
        return httpx.Response(200, json=RESPONSE)

    server = GenericHttpToolServer(_channel(_sut(), handler), default_metadata={"task_id": "t0"})
    server.ledger = _permissive_ledger()
    asyncio.run(server.sut_request("hi", metadata={"turn": 2}))
    assert captured["headers"]["x-trace"] == "t0"  # 模板吃到合并后的 metadata


def test_sut_request_channel_error_guarded_as_failed_result() -> None:
    """通道异常（AgentEvalError 族）经 tool_guard 转 failed 结果，不中断执行图。"""
    sut = _sut(
        request_template=RequestTemplateConfig(
            method="POST", path="/chat", body={"q": "{{ wrong_var }}"}
        )
    )

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover — 不应到达
        return httpx.Response(200, json=RESPONSE)

    server = GenericHttpToolServer(_channel(sut, handler))
    server.ledger = _permissive_ledger()
    result = asyncio.run(server.sut_request("hi"))
    assert result["status"] == "failed"
    assert "渲染失败" in result["error"]["message"]


# ── steps 链式请求（v4.8）：jxb 类「建会话 → 发消息 → 查历史」多步 API ────────


def _chain_sut(**kwargs) -> SUTSystemConfig:
    """三步链：create 建会话 → send 发消息（引用 create.data.id）→ history 查历史。"""
    steps = [
        RequestStepConfig(
            name="create", method="POST", path="/chat/conversations", body={"student_id": None}
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


def test_run_steps_chain_executes_in_order_and_extracts_last() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        if request.url.path == "/chat/conversations" and request.method == "POST":
            return httpx.Response(200, json={"data": {"id": "c1"}})
        if request.url.path == "/chat/conversations/c1/messages":
            return httpx.Response(200, json={"code": 0})
        return httpx.Response(
            200,
            json={
                "data": {
                    "messages": [
                        {"role": "user", "content": "霸凌计划"},
                        {"role": "assistant", "content": "拒绝回复"},
                    ]
                }
            },
        )

    result = asyncio.run(_channel(_chain_sut(), handler).run("霸凌计划", metadata={}))
    # 链值传递：send/history 两步的路径拿到了 create 步响应里的 id
    assert [r.url.path for r in captured] == [
        "/chat/conversations",
        "/chat/conversations/c1/messages",
        "/chat/conversations/c1",
    ]
    assert json.loads(captured[1].content) == {"content": "霸凌计划"}  # input 消费
    assert result["status"] == "success"
    assert result["text"] == "拒绝回复"  # response_mapping 作用于末步


def test_run_steps_chain_intermediate_error_fails_with_step_name() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/chat/conversations":
            return httpx.Response(200, json={"data": {"id": "c1"}})
        return httpx.Response(500, text="boom")

    result = asyncio.run(_channel(_chain_sut(), handler).run("hi", metadata={}))
    assert result["status"] == "failed"
    assert result["error"]["code"] == "http_500"
    assert result["error"]["message"].startswith("步骤 send: ")


def test_run_steps_chain_captures_non_json_step_as_text() -> None:
    """非 JSON 中间步（SSE 等）→ text 包装可被后续步引用。"""
    steps = [
        RequestStepConfig(name="create", method="POST", path="/start"),
        RequestStepConfig(
            name="send", method="POST", path="/relay", body={"echo": "{{ create.text }}"}
        ),
    ]
    sut = _chain_sut(
        request_template=RequestTemplateConfig(steps=steps), response_mapping={"text": "reply"}
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/start":
            return httpx.Response(200, text='data: {"type":"thought"}')  # SSE 原文
        return httpx.Response(200, json={"reply": json.loads(request.content)["echo"]})

    result = asyncio.run(_channel(sut, handler).run("hi", metadata={}))
    assert result["status"] == "success"
    assert result["text"] == 'data: {"type":"thought"}'


def test_run_sse_final_step_extracts_events() -> None:
    """SSE 末步：机械解析 data: 帧为 events 列表，mapping 按 events.N.字段提取。"""
    steps = [
        RequestStepConfig(name="create", method="POST", path="/chat/conversations"),
        RequestStepConfig(
            name="send",
            method="POST",
            path="/chat/conversations/{{ create.data.id }}/messages",
            body={"content": "{{ input }}"},
        ),
    ]
    sut = _chain_sut(
        request_template=RequestTemplateConfig(steps=steps),
        response_mapping={"text": "events.-1.content"},
    )
    sse_body = (
        'data: {"type":"message_start"}\n\n'
        'data: {"type":"answer","content":"拒绝回复"}\n\n'
        "data: [DONE]\n\n"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/chat/conversations" and request.method == "POST":
            return httpx.Response(200, json={"data": {"id": "c1"}})
        return httpx.Response(200, content=sse_body, headers={"content-type": "text/event-stream"})

    result = asyncio.run(_channel(sut, handler).run("hi", metadata={}))
    assert result["status"] == "success"
    assert result["text"] == "拒绝回复"


def test_run_text_path_resolves_null_maps_failed() -> None:
    """text 路径命中但取值 null = 配置变形，failed 而非静默整包兜底。"""
    sut = _chain_sut(response_mapping={"text": "data.messages.-1.content"})

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/chat/conversations" and request.method == "POST":
            return httpx.Response(200, json={"data": {"id": "c1"}})
        if request.url.path.endswith("/messages"):
            return httpx.Response(200, json={"code": 0})
        return httpx.Response(200, json={"data": {"messages": None}})

    result = asyncio.run(_channel(sut, handler).run("hi", metadata={}))
    assert result["status"] == "failed"
    assert result["error"]["code"] == "text_path_miss"


def test_run_steps_chain_health_check_validates_all_step_templates() -> None:
    sut = _chain_sut(
        request_template=RequestTemplateConfig(
            steps=[
                RequestStepConfig(name="a", method="POST", path="/{% if %}"),
                RequestStepConfig(name="b", method="GET", path="/ok"),
            ]
        )
    )

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover — 不应发请求
        raise AssertionError("health_check 不应发网络请求")

    with pytest.raises(SUTChannelError, match=r"steps\[0\]\.path 模板语法错误"):
        asyncio.run(_channel(sut, handler).health_check())


def test_sut_request_budget_gate_blocks_when_total_exhausted() -> None:
    """sut_call 动作（额度=sut_calls_total）：无 dispatch 单发限制，总额尽即拒。

    generic_http 一次任务常需多请求（链式 steps），不受 dispatch=1 约束；
    闸门在触网之前拒绝并给收尾指引（arch/16 §4.3）。
    """
    from agent_eval.agent.executor.ledger import EvidenceLedger, ResourceLedger
    from agent_eval.execution.models import InteractionPolicy

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=RESPONSE)

    server = GenericHttpToolServer(_channel(_sut(), handler), default_metadata={"task_id": "t0"})
    evidence = EvidenceLedger()
    server.ledger = ResourceLedger(
        InteractionPolicy(sut_calls_total=2, dispatch=1, nudges=1), evidence=evidence
    )

    for _ in range(2):
        assert asyncio.run(server.sut_request("hi"))["status"] == "success"

    refused = asyncio.run(server.sut_request("hi"))
    assert refused["status"] == "failed"
    assert refused["error"]["type"] == "BudgetExhausted"
    assert refused["error"]["budget"] == "sut_calls_total"
    assert "write_package" in refused["error"]["guidance"]
    assert any(e["kind"] == "sut_call" for e in evidence.events)


# ── once 会话续接（plan/06 M1）：sut_request 跨调用共享会话 ──────────────────


def _once_channel(handler) -> GenericHttpChannel:
    steps = [
        RequestStepConfig(name="create", method="POST", path="/chat/conversations", once=True),
        RequestStepConfig(
            name="send",
            method="POST",
            path="/chat/conversations/{{ create.data.id }}/messages",
            body={"content": "{{ input }}"},
        ),
    ]
    sut = _sut(
        request_template=RequestTemplateConfig(steps=steps),
        response_mapping={"text": "reply"},
    )
    return _channel(sut, handler)


def test_sut_request_session_continues_across_calls() -> None:
    """多轮 sut_request 自动续接：create 只在首轮执行（次轮仅 send）。"""
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        if request.url.path == "/chat/conversations":
            return httpx.Response(200, json={"data": {"id": "c1"}})
        return httpx.Response(200, json={"reply": f"回:{json.loads(request.content)['content']}"})

    server = GenericHttpToolServer(_once_channel(handler))
    server.current_session_key = "t1"
    server.ledger = _permissive_ledger()
    first = asyncio.run(server.sut_request("第一问"))
    second = asyncio.run(server.sut_request("第二问"))
    assert first["text"] == "回:第一问"
    assert second["text"] == "回:第二问"
    assert [r.url.path for r in captured] == [
        "/chat/conversations",
        "/chat/conversations/c1/messages",
        "/chat/conversations/c1/messages",  # 次轮仅 send——create 命中缓存
    ]


def test_sut_request_new_session_rebuilds_conversation() -> None:
    """new_session=True 显式换会话：create 重新执行。"""
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        if request.url.path == "/chat/conversations":
            return httpx.Response(200, json={"data": {"id": "c1"}})
        return httpx.Response(200, json={"reply": "ok"})

    server = GenericHttpToolServer(_once_channel(handler))
    server.current_session_key = "t1"
    server.ledger = _permissive_ledger()
    asyncio.run(server.sut_request("hi"))
    captured.clear()
    asyncio.run(server.sut_request("hi", new_session=True))
    assert captured[0].url.path == "/chat/conversations"


def test_sut_request_once_cache_hit_still_counts_sut_call() -> None:
    """once 次轮命中缓存跳过 create 请求，但仍计一次 sut_call（授权=尝试语义）。"""
    from agent_eval.agent.executor.ledger import EvidenceLedger, ResourceLedger
    from agent_eval.execution.models import InteractionPolicy

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/chat/conversations":
            return httpx.Response(200, json={"data": {"id": "c1"}})
        return httpx.Response(200, json={"reply": "ok"})

    server = GenericHttpToolServer(_once_channel(handler))
    server.current_session_key = "t1"
    evidence = EvidenceLedger()
    server.ledger = ResourceLedger(
        InteractionPolicy(sut_calls_total=2, dispatch=1, nudges=1), evidence=evidence
    )

    for _ in range(2):
        assert asyncio.run(server.sut_request("hi"))["status"] == "success"
    assert server.ledger is not None
    assert server.ledger.counters["sut_call"] == 2  # 次轮 create 跳过仍计数

    refused = asyncio.run(server.sut_request("hi"))
    assert refused["error"]["type"] == "BudgetExhausted"


def test_channel_aclose_clears_session_cache() -> None:
    """aclose 清会话缓存——会话属于单次评测运行，不跨运行存活。"""
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/chat/conversations":
            return httpx.Response(200, json={"data": {"id": "c1"}})
        return httpx.Response(200, json={"reply": "ok"})

    channel = _once_channel(handler)
    asyncio.run(channel.run("hi", metadata={}, session_key="t1"))
    assert len(channel._session) == 1  # noqa: SLF001

    asyncio.run(channel.aclose())
    assert len(channel._session) == 0  # noqa: SLF001
    seen.clear()  # aclose 后会话不存活：再次 run 需重建（仅验证缓存清空）


def test_sut_request_logs_sut_observation_event() -> None:
    """合同一（arch/16 §4.6）：generic_http 面同样落 sut_observation 观测事件。"""
    from agent_eval.agent.executor.ledger import EvidenceLedger, ResourceLedger
    from agent_eval.execution.models import InteractionPolicy

    evidence = EvidenceLedger()
    server = GenericHttpToolServer(
        _channel(_sut(), lambda request: httpx.Response(200, json=RESPONSE)),
        default_metadata={"task_id": "t0"},
    )
    server.ledger = ResourceLedger(InteractionPolicy(sut_calls_total=8), evidence=evidence)
    asyncio.run(server.sut_request("帮我生成课件"))
    observations = [e for e in evidence.events if e["kind"] == "sut_observation"]
    assert observations and observations[0]["source"] == "sut_request"
    assert observations[0]["terminal_kind"] == "delivered"
    assert "课件正文" in observations[0]["text"]
