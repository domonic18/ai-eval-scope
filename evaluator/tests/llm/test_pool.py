"""ProviderPool 测试。

池键 = LLM 角色名（注册表契约，config/llm_roles.py）：仅 chat 角色
（text/vision/agent）进池；decision 等专线角色由对应专线构造器消费。
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from agent_eval.config import LLMConfig, ProviderConfig
from agent_eval.core.exceptions import ProviderNotFoundError
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


def _role_config(provider: str, model: str) -> ProviderConfig:
    return ProviderConfig(provider=provider, model=model, api_key="k")


class TestProviderPool:
    """ProviderPool 测试（键为注册角色名）。"""

    def test_get_default(self) -> None:
        """获取默认 Provider。"""
        with patch("agent_eval.llm.pool.LLMClientFactory") as mock_factory:
            mock_factory.create.side_effect = [
                _make_mock_client("text", "deepseek-chat"),
                _make_mock_client("vision", "gpt-4"),
            ]
            config = LLMConfig(
                default="text",
                providers={
                    "text": _role_config("deepseek", "deepseek-chat"),
                    "vision": _role_config("openai", "gpt-4"),
                },
            )
            pool = ProviderPool(config)
            client = pool.get()
            assert client.provider_name == "text"

    def test_get_by_name(self) -> None:
        """按角色名获取 Provider。"""
        with patch("agent_eval.llm.pool.LLMClientFactory") as mock_factory:
            mock_factory.create.side_effect = [
                _make_mock_client("text", "deepseek-chat"),
                _make_mock_client("vision", "gpt-4"),
            ]
            config = LLMConfig(
                default="text",
                providers={
                    "text": _role_config("deepseek", "deepseek-chat"),
                    "vision": _role_config("openai", "gpt-4"),
                },
            )
            pool = ProviderPool(config)
            client = pool.get("vision")
            assert client.provider_name == "vision"
            assert client.model == "gpt-4"

    def test_get_nonexistent(self) -> None:
        """获取不存在的 Provider 抛 ProviderNotFoundError。"""
        with patch("agent_eval.llm.pool.LLMClientFactory") as mock_factory:
            mock_factory.create.return_value = _make_mock_client("text", "m")
            config = LLMConfig(
                default="text",
                providers={
                    "text": _role_config("deepseek", "m"),
                },
            )
            pool = ProviderPool(config)
            with pytest.raises(ProviderNotFoundError) as exc_info:
                pool.get("nonexistent")
            assert "nonexistent" in str(exc_info.value)
            assert "text" in exc_info.value.available

    def test_list_providers(self) -> None:
        """列出所有 Provider 信息。"""
        with patch("agent_eval.llm.pool.LLMClientFactory") as mock_factory:
            mock_factory.create.side_effect = [
                _make_mock_client("text", "deepseek-chat"),
                _make_mock_client("vision", "gpt-4", "openai"),
            ]
            config = LLMConfig(
                default="text",
                providers={
                    "text": _role_config("deepseek", "deepseek-chat"),
                    "vision": _role_config("openai", "gpt-4"),
                },
            )
            pool = ProviderPool(config)
            infos = pool.list_providers()
            assert len(infos) == 2
            names = {i.name for i in infos}
            assert names == {"text", "vision"}

    def test_default_property(self) -> None:
        """default 属性返回默认客户端。"""
        with patch("agent_eval.llm.pool.LLMClientFactory") as mock_factory:
            mock_factory.create.return_value = _make_mock_client("text", "m")
            config = LLMConfig(
                default="text",
                providers={
                    "text": _role_config("deepseek", "m"),
                },
            )
            pool = ProviderPool(config)
            assert pool.default.provider_name == "text"

    def test_default_name_property(self) -> None:
        """default_name 属性。"""
        with patch("agent_eval.llm.pool.LLMClientFactory") as mock_factory:
            mock_factory.create.return_value = _make_mock_client("agent", "m")
            config = LLMConfig(
                default="agent",
                providers={
                    "agent": _role_config("deepseek", "m"),
                },
            )
            pool = ProviderPool(config)
            assert pool.default_name == "agent"

    def test_non_chat_roles_never_enter_pool(self) -> None:
        """注册表派发：非 chat 角色（decision 等）不进池，也不误建 chat 客户端。"""
        with patch("agent_eval.llm.pool.LLMClientFactory") as mock_factory:
            mock_factory.create.return_value = _make_mock_client("text", "m")
            config = LLMConfig(
                default="text",
                providers={
                    "text": _role_config("deepseek", "m"),
                    "decision": _role_config("noul", "typesafe/jev-1.13"),
                    "unknown_role": _role_config("openai", "m2"),  # 未注册名保守跳过
                },
            )
            pool = ProviderPool(config)
            assert mock_factory.create.call_count == 1  # 仅 text 建客户端
            with pytest.raises(ProviderNotFoundError):
                pool.get("decision")
            with pytest.raises(ProviderNotFoundError):
                pool.get("unknown_role")
