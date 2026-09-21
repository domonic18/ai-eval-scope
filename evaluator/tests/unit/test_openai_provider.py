"""OpenAICompatClient 构造防线单测 — timeout 显式透传 + SDK 内层重试禁用。

本地 docker 栈回归事故（20260921）：SDK 默认 read 600s × 内层重试 2 次 × 外层重试链
= 单约束几十分钟无日志挂起。timeout/max_retries 必须在构造时显式收口。
"""

from __future__ import annotations

from agent_eval.config import ProviderConfig
from agent_eval.llm.providers.openai_compat import OpenAICompatClient


def _config() -> ProviderConfig:
    return ProviderConfig(
        provider="openai",
        model="kimi-k2.6",
        api_key="sk-test",
        base_url="https://x.openai.compat/v1",
        max_tokens=64,
    )


def test_default_timeout_180s() -> None:
    client = OpenAICompatClient("text", _config())
    timeout = client._client.timeout
    assert float(getattr(timeout, "read", timeout)) == 180.0


def test_sdk_inner_retries_disabled() -> None:
    # 重试单源化到本模块外层循环（有日志、有退避、次数可控），SDK 内层必须为 0
    client = OpenAICompatClient("text", _config())
    assert client._client.max_retries == 0
