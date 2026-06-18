"""LLM 配置模型与默认值。

定义 Provider 配置（ProviderConfig）和 LLM 模块总配置（LLMConfig），
以及 LLM Judge、稳定性控制、结构化输出、Langfuse 追踪等模块的默认参数。
使用 Pydantic BaseModel 以支持序列化和校验；默认值使用 frozen dataclass
集中管理，避免散落在各模块代码中 hardcode。

本模块位于 agent_eval.config 包下，作为统一的 LLM 相关配置中心，供 LLM 模块、
Judge 编排器、Langfuse 追踪等各处导入使用。
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
    """单个 LLM Provider 配置。

    注意：以下字段默认值为全系统 Provider 层默认值，主要供 YAML 配置缺省时使用。
    Judge 层（评审模板）有独立的默认值（见 JudgeDefaults），避免 Provider 与 Judge
    两个层面的参数互相干扰。
    """

    provider: str = Field(description="协议类型: deepseek | openai | anthropic")
    model: str = Field(description="模型 ID")
    api_key: str = Field(description="API Key（支持 ${ENV_VAR} 引用）")
    base_url: str | None = Field(default=None, description="API base URL")
    max_tokens: int = Field(
        default=4096,
        description="最大输出 token 数；决定 LLM 单次返回长度上限",
    )
    temperature: float = Field(
        default=0.0,
        ge=0.0,
        le=2.0,
        description="默认温度；0 表示确定性输出，越大随机性越强",
    )
    seed: int = Field(
        default=42,
        description="默认随机种子；配合 temperature=0 提高结果可复现性",
    )
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
    """LLM Judge 评审模板默认参数。

    这些默认值用于 JudgeTemplate 数据类及从 YAML prompt 模板加载时的缺省值。
    单个 prompt 模板可以通过 YAML 中的字段覆盖这些默认值，例如视觉评估模板通常
    将 num_samples 设为 1 以节省成本。
    """

    # temperature=0 表示让 LLM 以确定性方式输出评分，减少随机波动；
    # 若模型在 temperature=0 下仍不稳定，可通过 StabilityDefaults 多次采样平滑。
    temperature: float = 0.0
    # seed 起点；实际每次采样会在此基础上 +sample_index，保证多次采样既可控又有差异。
    seed: int = 42
    # num_samples 决定单个约束/模板一次 judge 调用会对同一份输入做几次 LLM 采样，
    # 最终取中位数作为得分。值越大成本越高、结果越稳定；值越低越便宜但波动更大。
    num_samples: int = 3
    # score_range 是各评分维度的默认取值范围，与 prompt 中要求的 0-10 分制对齐。
    score_range: tuple[float, float] = field(default_factory=lambda: (0.0, 10.0))


@dataclass(frozen=True)
class StabilityDefaults:
    """稳定性控制器默认参数。

    StabilityController 对同一次 judge 请求做多次独立采样，取中位数作为最终得分，
    并依据标准差判断置信度。这些参数控制采样的次数和置信度判定阈值。
    """

    # 默认采样次数；与 JudgeDefaults.num_samples 保持一致，避免两个地方配置冲突。
    # 若此处与模板级 num_samples 同时设置，以模板级为准。
    num_samples: int = 3
    # 置信度判定阈值：同一维度在多次采样中的标准差超过该值时，置信度标记为 low。
    # 值越小越严格，越大越宽松。1.5 对应 0-10 分制下约 15% 的波动容忍度。
    stddev_threshold: float = 1.5


@dataclass(frozen=True)
class StructuredOutputDefaults:
    """结构化输出解析器默认参数。

    StructuredOutputParser 负责从 LLM 响应中提取 JSON 并校验 schema。
    max_retries 供上层重试逻辑参考，表示解析失败时建议的最大重试次数。
    """

    # LLM 返回非标准 JSON 或 schema 校验失败时的最大重试次数；
    # 实际重试由调用方控制，此处仅提供默认值。
    max_retries: int = 3


@dataclass(frozen=True)
class LangfuseDefaults:
    """Langfuse 追踪默认参数。

    Langfuse 用于记录 LLM 调用链（trace/span/generation），便于观测和审计。
    实际启用仍需通过环境变量 LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY 配置。
    """

    # 未设置 LANGFUSE_HOST 环境变量时的默认 SaaS 端点。
    host: str = "https://cloud.langfuse.com"


@dataclass(frozen=True)
class JudgeRecordDefaults:
    """JudgeRecord 溯源记录默认参数。

    JudgeRecord 用于持久化一次 judge 调用的完整信息（模型、参数、结果、token 用量等）。
    这些默认值主要保证未显式赋值时记录仍能正常序列化/反序列化。
    """

    # 记录中保存的调用温度；实际值来自模板渲染后的 template.temperature。
    temperature: float = 0.0
    # 记录中保存的随机种子；实际值来自模板 seed，多次采样时仅保存基础 seed。
    seed: int = 42
    # 记录中保存的采样次数；实际值由 StabilityController 返回的 num_samples 决定。
    num_samples: int = 1


# 模块级单例，供各模块直接导入使用，避免重复构造。
JUDGE_DEFAULTS = JudgeDefaults()
STABILITY_DEFAULTS = StabilityDefaults()
STRUCTURED_OUTPUT_DEFAULTS = StructuredOutputDefaults()
LANGFUSE_DEFAULTS = LangfuseDefaults()
JUDGE_RECORD_DEFAULTS = JudgeRecordDefaults()

# Judge ID 时间戳格式，用于 evidence 文件名和溯源记录中的 judge_id。
# 精确到秒；同一秒内多次调用需通过 judge_id_suffix 避免文件名冲突。
JUDGE_ID_DATETIME_FORMAT: str = "%Y%m%d_%H%M%S"
