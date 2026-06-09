"""Provider Pool — 多 LLM 客户端管理。"""

from __future__ import annotations

from agent_eval.core.exceptions import ProviderNotFoundError
from agent_eval.llm.client import LLMClient
from agent_eval.llm.config import LLMConfig
from agent_eval.llm.factory import LLMClientFactory
from agent_eval.llm.models import ProviderInfo


class ProviderPool:
    """LLM Provider 池 — 管理多个已配置的 LLM 客户端。

    从 LLMConfig 初始化，支持按名称获取客户端、列出可用 Provider。
    """

    def __init__(self, config: LLMConfig) -> None:
        """从 LLMConfig 初始化所有 Provider。

        Args:
            config: LLM 模块总配置。
        """
        self._providers: dict[str, LLMClient] = {}
        self._default_name: str = config.default
        for name, pcfg in config.providers.items():
            self._providers[name] = LLMClientFactory.create(name, pcfg)

    def get(self, name: str | None = None) -> LLMClient:
        """获取指定名称的 Provider。

        Args:
            name: Provider 名称。None 返回默认 Provider。

        Returns:
            LLMClient 实例。

        Raises:
            ProviderNotFoundError: 名称不存在时。
        """
        key = name or self._default_name
        if key not in self._providers:
            raise ProviderNotFoundError(key, available=list(self._providers.keys()))
        return self._providers[key]

    def list_providers(self) -> list[ProviderInfo]:
        """列出所有已配置 Provider 的元信息。"""
        return [client.provider_info for client in self._providers.values()]

    @property
    def default(self) -> LLMClient:
        """获取默认 Provider。"""
        return self._providers[self._default_name]

    @property
    def default_name(self) -> str:
        """获取默认 Provider 名称。"""
        return self._default_name
