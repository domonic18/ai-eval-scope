"""AnthropicCompatClient 单测 — SDK 0.x/1.0 采样参数兼容（temperature 探测）。"""

from __future__ import annotations

from typing import Any

import pytest

from agent_eval.config import ProviderConfig
from agent_eval.llm.models import Message
from agent_eval.llm.providers import anthropic as anthropic_provider
from agent_eval.llm.providers.anthropic import AnthropicCompatClient


def _config() -> ProviderConfig:
    return ProviderConfig(
        provider="anthropic",
        model="kimi-k2.6",
        api_key="sk-test",
        base_url="https://x.anthropic.compat",
        max_tokens=64,
        temperature=0.0,
    )


class TestTimeout:
    """timeout 显式透传（本地 docker 栈回归事故：SDK 默认 read 600s × 重试链 = 几十分钟挂起）。"""

    @staticmethod
    def _effective_timeout(client: AnthropicCompatClient) -> float:
        # anthropic SDK 会把 float 包装成 httpx.Timeout（read/write 均为该值）
        timeout = client._client.timeout
        return float(getattr(timeout, "read", timeout))

    def test_default_180s_not_sdk_600s(self) -> None:
        client = AnthropicCompatClient("text", _config())
        assert self._effective_timeout(client) == 180.0

    def test_config_override(self) -> None:
        cfg = _config()
        cfg.timeout_sec = 30.0
        client = AnthropicCompatClient("text", cfg)
        assert self._effective_timeout(client) == 30.0


def _client_with_fake(
    monkeypatch: pytest.MonkeyPatch, calls: list[dict[str, Any]]
) -> AnthropicCompatClient:
    """构造真实 AnthropicCompatClient，但 SDK client 换成记录 kwargs 的替身。"""

    class _Response:
        content = [type("_Block", (), {"text": "pong"})()]
        usage = None
        model = "kimi-k2.6"

    class _Messages:
        def create(self, **kwargs: Any) -> _Response:
            calls.append(kwargs)
            return _Response()

    class _Client:
        messages = _Messages()

    client = AnthropicCompatClient("text", _config())
    monkeypatch.setattr(client, "_client", _Client())
    return client


@pytest.mark.parametrize("supports,expect_has_temperature", [(True, True), (False, False)])
def test_temperature_passed_only_when_sdk_supports(
    monkeypatch: pytest.MonkeyPatch, supports: bool, expect_has_temperature: bool
) -> None:
    """SDK 1.0（不支持采样参数）不传 temperature；0.x 照常传。"""
    monkeypatch.setattr(anthropic_provider, "_supports_temperature", lambda: supports)
    calls: list[dict[str, Any]] = []
    client = _client_with_fake(monkeypatch, calls)

    response = client.chat([Message(role="user", content="ping")])

    assert response.content == "pong"
    assert len(calls) == 1
    assert ("temperature" in calls[0]) is expect_has_temperature
    assert calls[0]["model"] == "kimi-k2.6"
    assert calls[0]["max_tokens"] == 64


def test_max_tokens_stop_reason_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """stop_reason=max_tokens → LLMResponseError（不再静默返回半截输出）。

    run 20260912_111958：线路侧 ~1024 token 截断的半截 JSON 一路穿到解析层，
    报成难懂的「JSON 解析失败」。截断必须在 provider 层显式报错。
    """
    from agent_eval.core.exceptions import LLMResponseError

    _Block = type("_Block", (), {"text": '{"partial":'})
    _Usage = type("_Usage", (), {"input_tokens": 100, "output_tokens": 64})
    _Response = type(
        "_Response",
        (),
        {
            "content": [_Block()],
            "stop_reason": "max_tokens",
            "usage": _Usage(),
            "model": "kimi-k2.6",
        },
    )

    class _Messages:
        def create(self, **kwargs: Any) -> _Response:
            return _Response()

    class _Client:
        messages = _Messages()

    client = AnthropicCompatClient("text", _config())
    monkeypatch.setattr(client, "_client", _Client())

    with pytest.raises(LLMResponseError, match="截断"):
        client.chat([Message(role="user", content="ping")])
