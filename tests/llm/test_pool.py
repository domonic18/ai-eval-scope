"""ProviderPool 测试。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from agent_eval.core.exceptions import ProviderNotFoundError
from agent_eval.llm.config import LLMConfig, ProviderConfig
from agent_eval.llm.models import ProviderInfo
from agent_eval.llm.pool import ProviderPool


def _make_mock_client(name: str, model: str, provider: str = "deepseek") -> MagicMock:
    """创建 Mock LLMClient。"""
    client = MagicMock()
    client.provider_name = name
    client.model = model
    client.provider_type = provider
    client.provider_info = ProviderInfo(name=name, model=model, provider=provider)
    return client


class TestProviderPool:
    """ProviderPool 测试。"""

    def test_get_default(self) -> None:
        """获取默认 Provider。"""
        with patch("agent_eval.llm.pool.LLMClientFactory") as mock_factory:
            mock_factory.create.side_effect = [
                _make_mock_client("ds", "deepseek-chat"),
                _make_mock_client("oai", "gpt-4"),
            ]
            config = LLMConfig(
                default="ds",
                providers={
                    "ds": ProviderConfig(provider="deepseek", model="deepseek-chat", api_key="k"),
                    "oai": ProviderConfig(provider="openai", model="gpt-4", api_key="k"),
                },
            )
            pool = ProviderPool(config)
            client = pool.get()
            assert client.provider_name == "ds"

    def test_get_by_name(self) -> None:
        """按名称获取 Provider。"""
        with patch("agent_eval.llm.pool.LLMClientFactory") as mock_factory:
            mock_factory.create.side_effect = [
                _make_mock_client("ds", "deepseek-chat"),
                _make_mock_client("oai", "gpt-4"),
            ]
            config = LLMConfig(
                default="ds",
                providers={
                    "ds": ProviderConfig(provider="deepseek", model="deepseek-chat", api_key="k"),
                    "oai": ProviderConfig(provider="openai", model="gpt-4", api_key="k"),
                },
            )
            pool = ProviderPool(config)
            client = pool.get("oai")
            assert client.provider_name == "oai"
            assert client.model == "gpt-4"

    def test_get_nonexistent(self) -> None:
        """获取不存在的 Provider 抛 ProviderNotFoundError。"""
        with patch("agent_eval.llm.pool.LLMClientFactory") as mock_factory:
            mock_factory.create.return_value = _make_mock_client("ds", "m")
            config = LLMConfig(
                default="ds",
                providers={
                    "ds": ProviderConfig(provider="deepseek", model="m", api_key="k"),
                },
            )
            pool = ProviderPool(config)
            with pytest.raises(ProviderNotFoundError) as exc_info:
                pool.get("nonexistent")
            assert "nonexistent" in str(exc_info.value)
            assert "ds" in exc_info.value.available

    def test_list_providers(self) -> None:
        """列出所有 Provider 信息。"""
        with patch("agent_eval.llm.pool.LLMClientFactory") as mock_factory:
            mock_factory.create.side_effect = [
                _make_mock_client("ds", "deepseek-chat"),
                _make_mock_client("oai", "gpt-4", "openai"),
            ]
            config = LLMConfig(
                default="ds",
                providers={
                    "ds": ProviderConfig(provider="deepseek", model="deepseek-chat", api_key="k"),
                    "oai": ProviderConfig(provider="openai", model="gpt-4", api_key="k"),
                },
            )
            pool = ProviderPool(config)
            infos = pool.list_providers()
            assert len(infos) == 2
            names = {i.name for i in infos}
            assert names == {"ds", "oai"}

    def test_default_property(self) -> None:
        """default 属性返回默认客户端。"""
        with patch("agent_eval.llm.pool.LLMClientFactory") as mock_factory:
            mock_factory.create.return_value = _make_mock_client("ds", "m")
            config = LLMConfig(
                default="ds",
                providers={
                    "ds": ProviderConfig(provider="deepseek", model="m", api_key="k"),
                },
            )
            pool = ProviderPool(config)
            assert pool.default.provider_name == "ds"

    def test_default_name_property(self) -> None:
        """default_name 属性。"""
        with patch("agent_eval.llm.pool.LLMClientFactory") as mock_factory:
            mock_factory.create.return_value = _make_mock_client("x", "m")
            config = LLMConfig(
                default="x",
                providers={
                    "x": ProviderConfig(provider="deepseek", model="m", api_key="k"),
                },
            )
            pool = ProviderPool(config)
            assert pool.default_name == "x"
