"""LLM 模块内部数据模型。

定义消息（Message）、Token 用量（TokenUsage）、LLM 响应（LLMResponse）、
Provider 信息（ProviderInfo）、评审溯源记录（JudgeRecord）等。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class TokenUsage:
    """Token 消耗统计。"""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    def to_dict(self) -> dict[str, Any]:
        """序列化为字典。"""
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TokenUsage:
        """从字典反序列化。"""
        return cls(**data)


@dataclass
class Message:
    """对话消息。"""

    role: str  # "system" | "user" | "assistant"
    content: str

    def to_dict(self) -> dict[str, Any]:
        """序列化为字典。"""
        return {
            "role": self.role,
            "content": self.content,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Message:
        """从字典反序列化。"""
        return cls(**data)


@dataclass
class LLMResponse:
    """LLM 响应 — 包含内容与溯源信息。"""

    content: str
    provider_name: str  # 使用的 Provider 名称，如 "deepseek_judge"
    model: str  # 实际模型 ID，如 "deepseek-chat"
    usage: TokenUsage | None = None
    raw_response: dict[str, Any] | None = None
    duration_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """序列化为字典。"""
        d: dict[str, Any] = {
            "content": self.content,
            "provider_name": self.provider_name,
            "model": self.model,
            "duration_ms": self.duration_ms,
        }
        if self.usage is not None:
            d["usage"] = self.usage.to_dict()
        if self.raw_response is not None:
            d["raw_response"] = self.raw_response
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LLMResponse:
        """从字典反序列化。"""
        data = dict(data)
        if "usage" in data and isinstance(data["usage"], dict):
            data["usage"] = TokenUsage.from_dict(data["usage"])
        return cls(**data)


@dataclass
class ProviderInfo:
    """Provider 元信息。"""

    name: str  # 配置名称，如 "deepseek_judge"
    model: str  # 模型 ID，如 "deepseek-chat"
    provider: str  # 协议类型，如 "deepseek" / "openai" / "anthropic"


@dataclass
class JudgeRecord:
    """单次 LLM Judge 调用的完整溯源记录。"""

    # 溯源标识
    judge_id: str  # 唯一标识，如 "judge_fmt001_20260608_143000"
    constraint_id: str  # 对应的约束 ID
    sample_id: str  # 对应的样本 ID
    # 模型信息
    provider_name: str  # 使用的 Provider，如 "deepseek_judge"
    model: str  # 实际模型 ID，如 "deepseek-chat"
    # 调用参数
    template_id: str  # 使用的 Prompt 模板
    temperature: float = 0.0
    seed: int = 42
    # 结果
    raw_response: str = ""
    parsed_scores: dict[str, Any] = field(default_factory=dict)
    final_scores: dict[str, Any] = field(default_factory=dict)
    confidence: dict[str, str] = field(default_factory=dict)  # dim_id -> "high" | "low"
    # LLM 评价总结（可解释性说明）
    summary: str = ""
    # 统计
    num_samples: int = 1
    total_duration_ms: float = 0.0
    token_usage: TokenUsage | None = None
    timestamp: str = ""  # ISO 8601

    def to_dict(self) -> dict[str, Any]:
        """序列化为字典。"""
        d: dict[str, Any] = {
            "judge_id": self.judge_id,
            "constraint_id": self.constraint_id,
            "sample_id": self.sample_id,
            "provider_name": self.provider_name,
            "model": self.model,
            "template_id": self.template_id,
            "temperature": self.temperature,
            "seed": self.seed,
            "raw_response": self.raw_response,
            "parsed_scores": self.parsed_scores,
            "final_scores": self.final_scores,
            "confidence": self.confidence,
            "num_samples": self.num_samples,
            "summary": self.summary,
            "total_duration_ms": self.total_duration_ms,
            "timestamp": self.timestamp,
        }
        if self.token_usage is not None:
            d["token_usage"] = self.token_usage.to_dict()
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> JudgeRecord:
        """从字典反序列化。"""
        data = dict(data)
        if "token_usage" in data and isinstance(data["token_usage"], dict):
            data["token_usage"] = TokenUsage.from_dict(data["token_usage"])
        return cls(**data)
