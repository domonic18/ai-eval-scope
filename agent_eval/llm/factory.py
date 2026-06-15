"""LLM 客户端工厂 — 按 Provider 类型创建对应客户端。"""

from __future__ import annotations

from agent_eval.core.exceptions import LLMError
from agent_eval.llm.client import LLMClient
from agent_eval.llm.config import ProviderConfig


def _check_openai_available() -> None:
    """检查 openai 库是否已安装。"""
    try:
        import openai  # noqa: F401
    except ImportError:
        raise LLMError(
            "使用 DeepSeek/OpenAI Provider 需要安装 openai 库。"
            "请执行: pip install 'agent-eval[llm]'",
            details={"missing_module": "openai"},
        ) from None


def _check_anthropic_available() -> None:
    """检查 anthropic 库是否已安装。"""
    try:
        import anthropic  # noqa: F401
    except ImportError:
        raise LLMError(
            "使用 Anthropic Provider 需要安装 anthropic 库。请执行: pip install 'agent-eval[llm]'",
            details={"missing_module": "anthropic"},
        ) from None


class LLMClientFactory:
    """LLM 客户端工厂。

    根据 ProviderConfig.provider 类型创建对应的 LLMClient 实例。
    """

    @staticmethod
    def create(name: str, config: ProviderConfig) -> LLMClient:
        """创建 LLM 客户端。

        Args:
            name: Provider 配置名称。
            config: Provider 配置。

        Returns:
            对应类型的 LLMClient 实例。

        Raises:
            LLMError: 不支持的 provider 类型或缺少依赖库。
        """
        if config.provider in ("deepseek", "openai"):
            _check_openai_available()
            from agent_eval.llm.providers.openai_compat import OpenAICompatClient

            return OpenAICompatClient(name, config)

        elif config.provider == "anthropic":
            _check_anthropic_available()
            from agent_eval.llm.providers.anthropic import AnthropicCompatClient

            return AnthropicCompatClient(name, config)

        else:
            raise LLMError(
                f"不支持的 provider 类型: {config.provider}",
                details={"supported": ["deepseek", "openai", "anthropic"]},
            )
