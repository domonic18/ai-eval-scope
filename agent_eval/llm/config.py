"""LLM 配置模型。

定义 Provider 配置（ProviderConfig）和 LLM 模块总配置（LLMConfig）。
使用 Pydantic BaseModel 以支持序列化和校验。
"""

from __future__ import annotations

import os
import re
from typing import Any

from pydantic import BaseModel, Field

# 匹配 ${ENV_VAR} 或 $ENV_VAR 格式
_ENV_VAR_PATTERN = re.compile(r"\$\{(\w+)\}|\$(\w+)")


def resolve_api_key(api_key: str) -> str:
    """解析 API Key 中的环境变量引用。

    支持格式：
      - ${DEEPSEEK_API_KEY}
      - $DEEPSEEK_API_KEY
      - 纯字符串（直接返回）

    Args:
        api_key: 可能包含环境变量引用的字符串。

    Returns:
        解析后的 API Key。

    Raises:
        ValueError: 环境变量未设置时。
    """
    def _replace(match: re.Match[str]) -> str:
        var_name = match.group(1) or match.group(2)
        value = os.environ.get(var_name)
        if value is None:
            raise ValueError(
                f"环境变量 {var_name} 未设置，无法解析 API Key"
            )
        return value

    return _ENV_VAR_PATTERN.sub(_replace, api_key)


class ProviderConfig(BaseModel):
    """单个 LLM Provider 配置。"""

    provider: str = Field(description="协议类型: deepseek | openai | anthropic")
    model: str = Field(description="模型 ID")
    api_key: str = Field(description="API Key（支持 ${ENV_VAR} 引用）")
    base_url: str | None = Field(default=None, description="API base URL")
    max_tokens: int = Field(default=4096, description="最大输出 token 数")
    temperature: float = Field(default=0.0, ge=0.0, le=2.0, description="默认温度")
    seed: int = Field(default=42, description="默认随机种子")
    extra_params: dict[str, Any] = Field(
        default_factory=dict, description="额外参数"
    )

    model_config = {"extra": "allow"}


class LLMConfig(BaseModel):
    """LLM 模块总配置。"""

    default: str = Field(description="默认 Provider 名称")
    providers: dict[str, ProviderConfig] = Field(
        description="Provider 配置映射，key 为 Provider 名称"
    )

    model_config = {"extra": "allow"}
