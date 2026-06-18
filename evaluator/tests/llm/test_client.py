"""LLMClient ABC 契约测试。"""

from __future__ import annotations

from typing import Any

import pytest

from agent_eval.llm.client import LLMClient
from agent_eval.llm.models import LLMResponse, Message, ProviderInfo


class ConcreteClient(LLMClient):
    """用于测试的具体客户端实现。"""

    def __init__(self, name: str = "test_provider", model_id: str = "test-model") -> None:
        self._name = name
        self._model = model_id

    @property
    def provider_name(self) -> str:
        return self._name

    @property
    def model(self) -> str:
        return self._model

    @property
    def provider_type(self) -> str:
        return "test"

    def chat(self, messages: list[Message], **kwargs: Any) -> LLMResponse:
        return LLMResponse(
            content="mock response",
            provider_name=self._name,
            model=self._model,
        )

    def chat_with_vision(
        self, messages: list[Message], images: list[str], **kwargs: Any
    ) -> LLMResponse:
        return LLMResponse(
            content="mock vision response",
            provider_name=self._name,
            model=self._model,
        )


class TestLLMClientABC:
    """LLMClient 抽象基类测试。"""

    def test_cannot_instantiate_abc(self) -> None:
        """不能直接实例化 ABC。"""
        with pytest.raises(TypeError):
            LLMClient()  # type: ignore[abstract]

    def test_concrete_subclass(self) -> None:
        """具体子类可实例化。"""
        client = ConcreteClient()
        assert client.provider_name == "test_provider"
        assert client.model == "test-model"
        assert client.provider_type == "test"

    def test_provider_info_property(self) -> None:
        """provider_info 返回 ProviderInfo。"""
        client = ConcreteClient("my_provider", "gpt-4")
        info = client.provider_info
        assert isinstance(info, ProviderInfo)
        assert info.name == "my_provider"
        assert info.model == "gpt-4"
        assert info.provider == "test"

    def test_chat_returns_llm_response(self) -> None:
        """chat() 返回 LLMResponse。"""
        client = ConcreteClient()
        messages = [Message(role="user", content="Hello")]
        resp = client.chat(messages)
        assert isinstance(resp, LLMResponse)
        assert resp.provider_name == "test_provider"
        assert resp.model == "test-model"

    def test_chat_with_vision(self) -> None:
        """chat_with_vision() 接收 images 参数。"""
        client = ConcreteClient()
        messages = [Message(role="user", content="Describe")]
        resp = client.chat_with_vision(messages, images=["http://img.url"])
        assert resp.content == "mock vision response"
