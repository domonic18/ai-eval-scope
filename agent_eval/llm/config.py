"""LLM 配置模型与默认值。

定义 Provider 配置（ProviderConfig）和 LLM 模块总配置（LLMConfig），
以及 LLM Judge、稳定性控制、结构化输出、Langfuse 追踪等模块的默认参数。
使用 Pydantic BaseModel 以支持序列化和校验；默认值使用 frozen dataclass
集中管理，避免散落在各模块代码中 hardcode。
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
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
            raise ValueError(f"环境变量 {var_name} 未设置，无法解析 API Key")
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
    extra_params: dict[str, Any] = Field(default_factory=dict, description="额外参数")

    model_config = {"extra": "allow"}


class LLMConfig(BaseModel):
    """LLM 模块总配置。"""

    default: str = Field(description="默认 Provider 名称")
    providers: dict[str, ProviderConfig] = Field(
        description="Provider 配置映射，key 为 Provider 名称"
    )

    model_config = {"extra": "allow"}


# =============================================================================
# LLM Judge 与相关模块默认值（集中管理，避免代码中 hardcode）
# =============================================================================


@dataclass(frozen=True)
class JudgeDefaults:
    """LLM Judge 评审模板默认参数。"""

    temperature: float = 0.0
    seed: int = 42
    num_samples: int = 3
    score_range: tuple[float, float] = field(default_factory=lambda: (0.0, 10.0))


@dataclass(frozen=True)
class StabilityDefaults:
    """稳定性控制器默认参数。"""

    num_samples: int = 3
    stddev_threshold: float = 1.5


@dataclass(frozen=True)
class StructuredOutputDefaults:
    """结构化输出解析器默认参数。"""

    max_retries: int = 3


@dataclass(frozen=True)
class LangfuseDefaults:
    """Langfuse 追踪默认参数。"""

    host: str = "https://cloud.langfuse.com"


@dataclass(frozen=True)
class JudgeRecordDefaults:
    """JudgeRecord 溯源记录默认参数。"""

    temperature: float = 0.0
    seed: int = 42
    num_samples: int = 1


# 模块级单例，供各模块直接导入使用
JUDGE_DEFAULTS = JudgeDefaults()
STABILITY_DEFAULTS = StabilityDefaults()
STRUCTURED_OUTPUT_DEFAULTS = StructuredOutputDefaults()
LANGFUSE_DEFAULTS = LangfuseDefaults()
JUDGE_RECORD_DEFAULTS = JudgeRecordDefaults()

# Judge ID 时间戳格式
JUDGE_ID_DATETIME_FORMAT: str = "%Y%m%d_%H%M%S"
