"""LLM 客户端工厂测试。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from agent_eval.core.exceptions import LLMError
from agent_eval.llm.config import ProviderConfig
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
        assert client.provider_type == "deepseek"
        assert client.model == "deepseek-chat"
        assert client.provider_name == "ds_judge"

    @patch("openai.OpenAI")
    def test_create_openai_compat(self, mock_openai_cls: MagicMock) -> None:
        """创建 OpenAI 兼容客户端（使用 DeepSeekClient）。"""
        config = ProviderConfig(
            provider="openai",
            model="gpt-4",
            api_key="sk-test",
        )
        client = LLMClientFactory.create("oai", config)
        assert client.provider_type == "deepseek"  # DeepSeekClient 也处理 openai 类型

    def test_create_anthropic_not_yet(self) -> None:
        """Anthropic 类型暂未实现，抛出 LLMError。"""
        with patch("agent_eval.llm.factory._check_anthropic_available"):
            config = ProviderConfig(
                provider="anthropic",
                model="kimi-2.6",
                api_key="sk-test",
            )
            with pytest.raises(LLMError, match="Sprint 6"):
                LLMClientFactory.create("kimi", config)

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
        config = ProviderConfig(
            provider="deepseek", model="m", api_key="k"
        )
        with patch("agent_eval.llm.factory._check_openai_available") as mock_check:
            mock_check.side_effect = LLMError(
                "使用 DeepSeek/OpenAI Provider 需要安装 openai 库。"
                "请执行: pip install 'agent-eval[llm]'",
                details={"missing_module": "openai"},
            )
            with pytest.raises(LLMError, match="openai"):
                LLMClientFactory.create("ds", config)
