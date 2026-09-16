"""评估侧数据模型。

定义约束结果（ConstraintResult）、阶段结果（StageResult）、
样本结果（SampleResult）、样本得分（SampleScore）、指标报告（MetricsReport）等。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agent_eval.core.types import ConstraintTier, EvalStatus


@dataclass
class ConstraintResult:
    """单项约束检查结果。"""

    constraint_id: str  # 如 "format.response_format"
    name: str
    tier: ConstraintTier
    status: EvalStatus
    score: float = 0.0  # 归一化后
    raw_score: float | None = None  # 原始得分
    reason: str = ""
    details: dict[str, Any] = field(default_factory=dict)
    duration_ms: float = 0.0
    # LLM Judge 溯源字段（仅 LLM 类评估器填充）
    judge_provider: str | None = None  # 使用的 Provider 名称，如 "deepseek_judge"
    judge_model: str | None = None  # 实际模型 ID，如 "deepseek-chat"
    judge_record_path: str | None = None  # 溯源记录文件路径
    # 目录模式可选字段
    module_results: list[dict[str, Any]] | None = None

    def to_dict(self) -> dict[str, Any]:
        """序列化为字典。"""
        d: dict[str, Any] = {
            "constraint_id": self.constraint_id,
            "name": self.name,
            "tier": self.tier.value,
            "status": self.status.value,
            "score": self.score,
            "raw_score": self.raw_score,
            "reason": self.reason,
            "details": self.details,
            "duration_ms": self.duration_ms,
            "judge_provider": self.judge_provider,
            "judge_model": self.judge_model,
            "judge_record_path": self.judge_record_path,
        }
        if self.module_results is not None:
            d["module_results"] = self.module_results
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ConstraintResult:
        """从字典反序列化。"""
        data = dict(data)  # 浅拷贝避免修改原数据
        data["tier"] = ConstraintTier(data["tier"])
        data["status"] = EvalStatus(data["status"])
        return cls(**data)


@dataclass
class StageResult:
    """一个阶段（Stage）的评估结果。"""

    stage_id: str  # "format" | "commonsense" | "quality"
    status: EvalStatus
    constraint_results: list[ConstraintResult] = field(default_factory=list)
    duration_ms: float = 0.0
    gate_passed: bool = True
    category_score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """序列化为字典。"""
        return {
            "stage_id": self.stage_id,
            "status": self.status.value,
            "constraint_results": [cr.to_dict() for cr in self.constraint_results],
            "duration_ms": self.duration_ms,
            "gate_passed": self.gate_passed,
            "category_score": self.category_score,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StageResult:
        """从字典反序列化。"""
        data = dict(data)
        data["status"] = EvalStatus(data["status"])
        data["constraint_results"] = [
            ConstraintResult.from_dict(cr) for cr in data.get("constraint_results", [])
        ]
        return cls(**data)


@dataclass
class SampleResult:
    """单个样本的完整评估结果。"""

    sample_id: str
    status: EvalStatus
    content_hash: str | None = None
    stage_results: dict[str, StageResult] = field(default_factory=dict)
    # 场景化样本级指标：由 ScenarioScoreAggregator.aggregate() 输出，
    # key = StageWeight.id（courseware 下为 soft/pref）+ "reward"。
    # 替代旧 s_format/s_common/s_soft/s_pref 标量（已废弃，dict 化以支持任意场景）。
    stage_metrics: dict[str, float] = field(default_factory=dict)
    reward: float = 0.0
    total_duration_ms: float = 0.0
    llm_calls: int = 0
    token_usage: int = 0
    # 执行链路过程指标（Sprint 9 v6.0：Steps/Turns、Tool Calls、Latency 落库）。
    # 由 orchestrator 从 ExecutionPackage 的 trace/metrics 注入（缓存命中路径同样生效）；
    # eval_only 的外部包无执行链路时保持 0。
    agent_turns: int = 0
    agent_tool_calls: int = 0
    agent_exec_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """序列化为字典。"""
        return {
            "sample_id": self.sample_id,
            "content_hash": self.content_hash,
            "status": self.status.value,
            "stage_results": {k: v.to_dict() for k, v in self.stage_results.items()},
            "stage_metrics": dict(self.stage_metrics),
            "reward": self.reward,
            "total_duration_ms": self.total_duration_ms,
            "llm_calls": self.llm_calls,
            "token_usage": self.token_usage,
            "agent_turns": self.agent_turns,
            "agent_tool_calls": self.agent_tool_calls,
            "agent_exec_ms": self.agent_exec_ms,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SampleResult:
        """从字典反序列化。

        兼容旧格式：若含已废弃的 s_format/s_common/s_soft/s_pref 标量字段则丢弃
        （新模型以 stage_metrics dict 为准；旧缓存条目因缺失 stage_metrics 将重算填充）。
        """
        data = dict(data)
        for legacy in ("s_format", "s_common", "s_soft", "s_pref"):
            data.pop(legacy, None)
        data["status"] = EvalStatus(data["status"])
        data["stage_results"] = {
            k: StageResult.from_dict(v) for k, v in data.get("stage_results", {}).items()
        }
        data.setdefault("stage_metrics", {})
        return cls(**data)


@dataclass
class SampleScore:
    """单个样本的评分快照。"""

    sample_id: str
    s_format: float = 0.0
    s_common: float = 0.0
    s_soft: float = 0.0
    s_pref: float = 0.0
    reward: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """序列化为字典。"""
        return {
            "sample_id": self.sample_id,
            "s_format": self.s_format,
            "s_common": self.s_common,
            "s_soft": self.s_soft,
            "s_pref": self.s_pref,
            "reward": self.reward,
        }


@dataclass
class MetricsReport:
    """批量评估的汇总指标报告。"""

    run_id: str
    total_samples: int = 0
    # 场景化运行级指标：key = MetricDefinition.id（如 courseware:document_rate），
    # 由 ScenarioMetricsCalculator.compute() 按 expression 求值输出。替代旧 dr/cpr/avg_*。
    metrics: dict[str, float] = field(default_factory=dict)
    # 指标定义快照（name/threshold/summary/explain 等），供报告渲染与下游展示
    metric_definitions: list[dict[str, Any]] = field(default_factory=list)
    avg_time_ms: float = 0.0  # 平均耗时（过程元数据，不进入质量指标 dict）
    sample_scores: list[dict[str, Any]] = field(default_factory=list)
    failure_breakdown: dict[str, int] = field(default_factory=dict)
    thresholds: dict[str, dict[str, Any]] = field(default_factory=dict)
    llm_skipped: int = 0  # 因 LLM 不可用而跳过的约束数

    def to_dict(self) -> dict[str, Any]:
        """序列化为字典。"""
        return {
            "run_id": self.run_id,
            "total_samples": self.total_samples,
            "metrics": dict(self.metrics),
            "metric_definitions": list(self.metric_definitions),
            "avg_time_ms": self.avg_time_ms,
            "thresholds": self.thresholds,
            "failure_breakdown": self.failure_breakdown,
            "sample_scores": list(self.sample_scores),
            "llm_skipped": self.llm_skipped,
        }
