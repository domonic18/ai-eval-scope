"""LLM 客户端抽象基类。

定义 LLMClient ABC，所有 Provider 实现必须继承此类。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from agent_eval.llm.models import LLMResponse, Message, ProviderInfo


class LLMClient(ABC):
    """LLM 客户端抽象基类。

    子类必须实现 chat() 和 chat_with_vision() 方法。
    """

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Provider 配置名称，如 "deepseek_judge"。"""
        ...

    @property
    @abstractmethod
    def model(self) -> str:
        """实际模型 ID，如 "deepseek-chat"。"""
        ...

    @property
    @abstractmethod
    def provider_type(self) -> str:
        """协议类型，如 "deepseek" / "openai" / "anthropic"。"""
        ...

    @abstractmethod
    def chat(self, messages: list[Message], **kwargs: Any) -> LLMResponse:
        """发送对话请求。

        Args:
            messages: 消息列表。
            **kwargs: 覆盖参数（seed, temperature, max_tokens 等）。

        Returns:
            LLMResponse 实例。
        """
        ...

    @abstractmethod
    def chat_with_vision(
        self, messages: list[Message], images: list[str], **kwargs: Any
    ) -> LLMResponse:
        """发送多模态请求（文本+图片）。

        Args:
            messages: 消息列表。
            images: 图片 URL 或 base64 编码列表。
            **kwargs: 覆盖参数。

        Returns:
            LLMResponse 实例。
        """
        ...

    @property
    def provider_info(self) -> ProviderInfo:
        """获取 Provider 元信息。"""
        return ProviderInfo(
            name=self.provider_name,
            model=self.model,
            provider=self.provider_type,
        )
