"""OpenAI 兼容协议 LLM 客户端 — 使用 openai 库。

适用于所有 OpenAI Chat Completions 协议兼容的 API 服务，包括但不限于：
OpenAI 官方、DeepSeek、Moonshot（OpenAI 端点）、vLLM、Together 等。

`provider="openai"` 为通用协议值（base_url 由配置指定或使用 openai SDK 默认）；
`provider="deepseek"` 为便捷别名，未指定 base_url 时预置 DeepSeek 端点。
两者复用同一客户端类，差异仅在 base_url 默认值。
"""

from __future__ import annotations

import time
from typing import Any

import openai

from agent_eval.config import ProviderConfig, resolve_api_key
from agent_eval.core.exceptions import (
    LLMAuthError,
    LLMError,
    LLMNetworkError,
    LLMQuotaExceededError,
    LLMRateLimitError,
)
from agent_eval.llm.client import LLMClient
from agent_eval.llm.models import LLMResponse, Message, TokenUsage

# DeepSeek 便捷别名预置的端点
_DEEPSEEK_DEFAULT_BASE_URL = "https://api.deepseek.com/v1"

# 瞬时错误重试参数（网络超时/连接失败/限流/5xx）
_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 1.0


def _is_retryable(e: openai.APIError) -> bool:
    """判断 OpenAI SDK 异常是否值得重试（瞬时错误）。"""
    if isinstance(e, openai.APITimeoutError | openai.APIConnectionError):
        return True
    if isinstance(e, openai.RateLimitError):
        msg = str(e).lower()
        return "insufficient_quota" not in msg and "billing" not in msg
    if isinstance(e, openai.APIStatusError):
        return e.status_code >= 500
    return False


def _map_openai_error(e: openai.APIError, name: str, model: str) -> LLMError:
    """将 OpenAI SDK 异常映射为 LLM 分级异常。"""
    details = {"provider": name, "model": model}
    if isinstance(e, openai.APITimeoutError):
        return LLMNetworkError(f"OpenAI 请求超时: {e}", details=details)
    if isinstance(e, openai.APIConnectionError):
        return LLMNetworkError(f"OpenAI 连接失败: {e}", details=details)
    if isinstance(e, openai.AuthenticationError):
        return LLMAuthError(f"OpenAI 鉴权失败: {e}", details=details)
    if isinstance(e, openai.RateLimitError):
        msg = str(e).lower()
        if "insufficient_quota" in msg or "billing" in msg:
            return LLMQuotaExceededError(f"OpenAI 额度耗尽: {e}", details=details)
        return LLMRateLimitError(f"OpenAI 限流: {e}", details=details)
    if isinstance(e, openai.APIStatusError):
        d = {**details, "status": e.status_code}
        if e.status_code >= 500:
            return LLMNetworkError(f"OpenAI 服务端错误 {e.status_code}: {e}", details=d)
        return LLMError(f"OpenAI API 状态错误 {e.status_code}: {e}", details=d)
    return LLMError(f"OpenAI 兼容 API 调用失败: {e}", details=details)


class OpenAICompatClient(LLMClient):
    """OpenAI 兼容协议客户端 — 基于 openai 库。

    适用于所有 OpenAI Chat Completions 协议兼容的 API 服务。
    """

    def __init__(self, name: str, config: ProviderConfig) -> None:
        self._name = name
        self._config = config
        # deepseek 别名未指定 base_url 时预置 DeepSeek 端点；
        # openai 通用协议未指定时由 openai SDK 使用其默认端点
        base_url = config.base_url
        if not base_url and config.provider == "deepseek":
            base_url = _DEEPSEEK_DEFAULT_BASE_URL
        self._client = openai.OpenAI(
            api_key=resolve_api_key(config.api_key),
            base_url=base_url,
        )

    @property
    def provider_name(self) -> str:
        return self._name

    @property
    def model(self) -> str:
        return self._config.model

    @property
    def provider_type(self) -> str:
        # 协议类型：openai 兼容协议统一返回 "openai"（而非具体厂商）
        return "openai"

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
        response = None
        for attempt in range(_MAX_RETRIES + 1):
            try:
                response = self._client.chat.completions.create(
                    model=self._config.model,
                    messages=[m.to_dict() for m in messages],
                    max_tokens=kwargs.get("max_tokens", self._config.max_tokens),
                    temperature=kwargs.get("temperature", self._config.temperature),
                    seed=kwargs.get("seed", self._config.seed),
                )
                break
            except openai.APIError as e:
                # 瞬时错误（超时/连接/限流/5xx）指数退避重试；不可重试或耗尽则映射抛出
                if attempt < _MAX_RETRIES and _is_retryable(e):
                    time.sleep(_RETRY_BASE_DELAY * (2 ** attempt))
                    continue
                raise _map_openai_error(e, self._name, self._config.model) from e

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
                    content_parts.append(
                        {
                            "type": "image_url",
                            "image_url": {"url": img},
                        }
                    )
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
                f"OpenAI 兼容 Vision API 调用失败: {e}",
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


# 向后兼容别名：历史代码可能 import DeepSeekClient
DeepSeekClient = OpenAICompatClient
