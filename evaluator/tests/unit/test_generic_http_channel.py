"""GenericHttpChannel 测试（arch/03 §4.2）——httpx.MockTransport 全离线。"""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from agent_eval.agent.executor.http_tools import GenericHttpToolServer
from agent_eval.core.exceptions import SUTChannelError
from agent_eval.execution.channels.base import create_channel
from agent_eval.execution.channels.generic_http import GenericHttpChannel
from agent_eval.execution.registry import RequestTemplateConfig, SUTSystemConfig


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


def test_run_text_falls_back_to_full_body_when_path_misses() -> None:
    sut = _sut(response_mapping={"text": "data.answer"})

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": "shape"})

    result = asyncio.run(_channel(sut, handler).run("hi", metadata={"task_id": "t0"}))
    assert result["status"] == "success"
    assert "unexpected" in result["text"]  # 路径未命中 → 整个响应体兜底
    assert result["output"]["files"] == []


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


def test_sut_request_returns_result_and_records_last_run() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=RESPONSE)

    server = GenericHttpToolServer(_channel(_sut(), handler), default_metadata={"task_id": "t0"})
    result = asyncio.run(server.sut_request("帮我生成课件"))
    assert result["status"] == "success"
    assert result["text"] == "课件正文"
    assert server.last_run == {"status": "success", "run_id": None, "text": "课件正文"}


def test_sut_request_merges_default_and_call_metadata() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["headers"] = dict(request.headers)
        return httpx.Response(200, json=RESPONSE)

    server = GenericHttpToolServer(_channel(_sut(), handler), default_metadata={"task_id": "t0"})
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
    result = asyncio.run(server.sut_request("hi"))
    assert result["status"] == "failed"
    assert "渲染失败" in result["error"]["message"]
