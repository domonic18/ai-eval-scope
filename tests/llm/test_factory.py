"""LLM 客户端工厂测试。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from agent_eval.config import ProviderConfig
from agent_eval.core.exceptions import LLMError
from agent_eval.llm.factory import LLMClientFactory


class TestLLMClientFactory:
    """LLMClientFactory 测试。"""

    @patch("openai.OpenAI")
    def test_create_deepseek(self, mock_openai_cls: MagicMock) -> None:
        """创建 DeepSeek 客户端。"""
        config = ProviderConfig(
            provider="deepseek",
            model="deepseek-chat",
            api_key="sk-test",
            base_url="https://api.deepseek.com/v1",
        )
        client = LLMClientFactory.create("ds_judge", config)
        assert client.provider_type == "openai"  # deepseek 走 openai 兼容协议
        assert client.model == "deepseek-chat"
        assert client.provider_name == "ds_judge"

    @patch("openai.OpenAI")
    def test_create_openai_compat(self, mock_openai_cls: MagicMock) -> None:
        """创建 OpenAI 兼容客户端（OpenAICompatClient 处理 openai 类型）。"""
        config = ProviderConfig(
            provider="openai",
            model="gpt-4",
            api_key="sk-test",
        )
        client = LLMClientFactory.create("oai", config)
        assert client.provider_type == "openai"  # 协议类型为 openai

    @patch("anthropic.Anthropic")
    def test_create_anthropic(self, mock_anthropic_cls: MagicMock) -> None:
        """创建 Anthropic 兼容客户端。"""
        config = ProviderConfig(
            provider="anthropic",
            model="kimi-2.6",
            api_key="sk-test",
            base_url="https://api.moonshot.cn/anthropic",
        )
        client = LLMClientFactory.create("kimi_vision", config)
        assert client.provider_type == "anthropic"
        assert client.model == "kimi-2.6"
        assert client.provider_name == "kimi_vision"

    def test_unsupported_provider(self) -> None:
        """不支持的 provider 类型抛出 LLMError。"""
        config = ProviderConfig(
            provider="unknown_vendor",
            model="m",
            api_key="k",
        )
        with pytest.raises(LLMError, match="不支持的 provider"):
            LLMClientFactory.create("bad", config)

    def test_missing_openai_library(self) -> None:
        """openai 库未安装时抛出 LLMError 含安装提示。"""
        config = ProviderConfig(provider="deepseek", model="m", api_key="k")
        with patch("agent_eval.llm.factory._check_openai_available") as mock_check:
            mock_check.side_effect = LLMError(
                "使用 DeepSeek/OpenAI Provider 需要安装 openai 库。"
                "请执行: pip install 'agent-eval[llm]'",
                details={"missing_module": "openai"},
            )
            with pytest.raises(LLMError, match="openai"):
                LLMClientFactory.create("ds", config)
