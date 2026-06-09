"""DeepSeek LLM 客户端 — 使用 openai 库兼容模式。"""

from __future__ import annotations

import time
from typing import Any

import openai

from agent_eval.core.exceptions import LLMError
from agent_eval.llm.client import LLMClient
from agent_eval.llm.config import ProviderConfig, resolve_api_key
from agent_eval.llm.models import LLMResponse, Message, TokenUsage


class DeepSeekClient(LLMClient):
    """DeepSeek 客户端 — 基于 openai 库兼容模式。

    适用于 DeepSeek 以及所有 OpenAI 兼容协议的 API 服务。
    """

    def __init__(self, name: str, config: ProviderConfig) -> None:
        self._name = name
        self._config = config
        self._client = openai.OpenAI(
            api_key=resolve_api_key(config.api_key),
            base_url=config.base_url or "https://api.deepseek.com/v1",
        )

    @property
    def provider_name(self) -> str:
        return self._name

    @property
    def model(self) -> str:
        return self._config.model

    @property
    def provider_type(self) -> str:
        return "deepseek"

    def chat(self, messages: list[Message], **kwargs: Any) -> LLMResponse:
        """发送对话请求。

        Args:
            messages: 消息列表。
            **kwargs: 覆盖参数（seed, temperature, max_tokens）。

        Returns:
            LLMResponse 实例。

        Raises:
            LLMError: API 调用失败时。
        """
        start = time.monotonic()
        try:
            response = self._client.chat.completions.create(
                model=self._config.model,
                messages=[m.to_dict() for m in messages],
                max_tokens=kwargs.get("max_tokens", self._config.max_tokens),
                temperature=kwargs.get("temperature", self._config.temperature),
                seed=kwargs.get("seed", self._config.seed),
            )
        except openai.APIError as e:
            raise LLMError(
                f"DeepSeek API 调用失败: {e}",
                details={"provider": self._name, "model": self._config.model},
            ) from e

        duration_ms = (time.monotonic() - start) * 1000

        content = response.choices[0].message.content or ""
        usage = None
        if response.usage:
            usage = TokenUsage(
                prompt_tokens=response.usage.prompt_tokens,
                completion_tokens=response.usage.completion_tokens,
                total_tokens=response.usage.total_tokens,
            )

        return LLMResponse(
            content=content,
            provider_name=self._name,
            model=self._config.model,
            usage=usage,
            raw_response=response.model_dump(),
            duration_ms=duration_ms,
        )

    def chat_with_vision(
        self, messages: list[Message], images: list[str], **kwargs: Any
    ) -> LLMResponse:
        """发送多模态请求（文本+图片）。

        将图片作为 image_url content block 附加到最后一条用户消息。
        """
        # 构建包含图片的消息
        openai_messages: list[dict[str, Any]] = []
        for i, msg in enumerate(messages):
            if i == len(messages) - 1 and msg.role == "user" and images:
                # 最后一条用户消息附带图片
                content_parts: list[dict[str, Any]] = [
                    {"type": "text", "text": msg.content},
                ]
                for img in images:
                    content_parts.append({
                        "type": "image_url",
                        "image_url": {"url": img},
                    })
                openai_messages.append({"role": msg.role, "content": content_parts})
            else:
                openai_messages.append(msg.to_dict())

        start = time.monotonic()
        try:
            response = self._client.chat.completions.create(
                model=self._config.model,
                messages=openai_messages,
                max_tokens=kwargs.get("max_tokens", self._config.max_tokens),
                temperature=kwargs.get("temperature", self._config.temperature),
                seed=kwargs.get("seed", self._config.seed),
            )
        except openai.APIError as e:
            raise LLMError(
                f"DeepSeek Vision API 调用失败: {e}",
                details={"provider": self._name, "model": self._config.model},
            ) from e

        duration_ms = (time.monotonic() - start) * 1000

        content = response.choices[0].message.content or ""
        usage = None
        if response.usage:
            usage = TokenUsage(
                prompt_tokens=response.usage.prompt_tokens,
                completion_tokens=response.usage.completion_tokens,
                total_tokens=response.usage.total_tokens,
            )

        return LLMResponse(
            content=content,
            provider_name=self._name,
            model=self._config.model,
            usage=usage,
            raw_response=response.model_dump(),
            duration_ms=duration_ms,
        )
