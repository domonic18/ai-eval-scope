"""Anthropic 兼容协议 LLM 客户端 — 使用 anthropic 库。

适用于所有 Anthropic Messages API 协议兼容的服务，包括但不限于：
Anthropic 官方、Kimi（月之暗面）、智谱 GLM、MiniMax 等（通过自定义 base_url 接入）。

协议要点（与 OpenAI 兼容协议的差异）：
- `system` 是 messages.create 的顶层参数，而非 messages 中的 role；
- `max_tokens` 必填；
- 不支持 `seed`（确定性依赖 temperature=0）；
- usage 字段为 input_tokens / output_tokens，无 total_tokens（需自行相加）；
- 多模态图片为 content block：{"type":"image","source":{...}}。
"""

from __future__ import annotations

import time
from typing import Any

import anthropic

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


def _split_system(messages: list[Message]) -> tuple[str | None, list[dict[str, Any]]]:
    """从消息列表中分离 system 消息（Anthropic 的 system 是顶层参数）。"""
    system_parts: list[str] = []
    convo: list[dict[str, Any]] = []
    for msg in messages:
        if msg.role == "system":
            system_parts.append(msg.content)
        else:
            convo.append({"role": msg.role, "content": msg.content})
    system = "\n\n".join(system_parts) if system_parts else None
    return system, convo


def _build_image_block(img: str) -> dict[str, Any]:
    """将图片引用构建为 Anthropic image content block。

    支持两种形式：
    - data URI（data:image/png;base64,...）→ base64 source；
    - http(s) URL → url source。
    """
    if img.startswith("data:"):
        header, _, data = img.partition(",")
        media_type = "image/png"
        if ";base64" in header:
            # data:<media_type>;base64
            media_type = header[5:].split(";")[0] or media_type
        return {
            "type": "image",
            "source": {"type": "base64", "media_type": media_type, "data": data},
        }
    return {"type": "image", "source": {"type": "url", "url": img}}


class AnthropicCompatClient(LLMClient):
    """Anthropic 兼容协议客户端 — 基于 anthropic 库。

    适用于所有 Anthropic Messages API 协议兼容的服务。
    """

    def __init__(self, name: str, config: ProviderConfig) -> None:
        self._name = name
        self._config = config
        self._client = anthropic.Anthropic(
            api_key=resolve_api_key(config.api_key),
            base_url=config.base_url,
        )

    @property
    def provider_name(self) -> str:
        return self._name

    @property
    def model(self) -> str:
        return self._config.model

    @property
    def provider_type(self) -> str:
        return "anthropic"

    def _call(
        self, messages: list[Message], images: list[str] | None, **kwargs: Any
    ) -> LLMResponse:
        """统一调用入口（chat 与 chat_with_vision 共用）。"""
        system, convo = _split_system(messages)
        # Anthropic 不支持 seed，丢弃（上层 judge() 会传 seed）
        kwargs.pop("seed", None)
        max_tokens = kwargs.get("max_tokens", self._config.max_tokens)
        temperature = kwargs.get("temperature", self._config.temperature)

        # 视觉：把图片块附加到最后一条 user 消息
        if images:
            for i in range(len(convo) - 1, -1, -1):
                if convo[i]["role"] == "user":
                    content: list[dict[str, Any]] = [{"type": "text", "text": convo[i]["content"]}]
                    content.extend(_build_image_block(img) for img in images)
                    convo[i] = {"role": "user", "content": content}
                    break

        request_kwargs: dict[str, Any] = {
            "model": self._config.model,
            "max_tokens": max_tokens,
            "messages": convo,
            "temperature": temperature,
        }
        if system is not None:
            request_kwargs["system"] = system

        start = time.monotonic()
        try:
            response = self._client.messages.create(**request_kwargs)
        except anthropic.APIError as e:
            msg = str(e).lower()
            status = getattr(e, "status_code", None)
            details = {"provider": self._name, "model": self._config.model, "status": status}
            if "insufficient_quota" in msg or "billing" in msg or "balance" in msg:
                raise LLMQuotaExceededError(
                    f"Anthropic 额度耗尽: {e}", details=details
                ) from e
            if status == 401 or "authentication" in msg or "api key" in msg:
                raise LLMAuthError(
                    f"Anthropic 鉴权失败: {e}", details=details
                ) from e
            if status == 429 or "rate" in msg:
                raise LLMRateLimitError(
                    f"Anthropic 限流: {e}", details=details
                ) from e
            if status and status >= 500:
                raise LLMNetworkError(
                    f"Anthropic 服务端错误 {status}: {e}", details=details
                ) from e
            if "timeout" in msg or "connection" in msg:
                raise LLMNetworkError(
                    f"Anthropic 连接错误: {e}", details=details
                ) from e
            raise LLMError(
                f"Anthropic 兼容 API 调用失败: {e}", details=details
            ) from e

        duration_ms = (time.monotonic() - start) * 1000

        # 提取文本（content 是 block 列表，取第一个 text 块）
        content_text = ""
        if response.content:
            for block in response.content:
                text = getattr(block, "text", None)
                if text:
                    content_text = text
                    break

        usage = None
        if response.usage:
            inp = getattr(response.usage, "input_tokens", 0) or 0
            out = getattr(response.usage, "output_tokens", 0) or 0
            usage = TokenUsage(
                prompt_tokens=inp,
                completion_tokens=out,
                total_tokens=inp + out,
            )

        return LLMResponse(
            content=content_text,
            provider_name=self._name,
            model=self._config.model,
            usage=usage,
            raw_response=response.model_dump() if hasattr(response, "model_dump") else None,
            duration_ms=duration_ms,
        )

    def chat(self, messages: list[Message], **kwargs: Any) -> LLMResponse:
        """发送对话请求。"""
        return self._call(messages, None, **kwargs)

    def chat_with_vision(
        self, messages: list[Message], images: list[str], **kwargs: Any
    ) -> LLMResponse:
        """发送多模态请求（文本+图片）。"""
        return self._call(messages, images, **kwargs)
