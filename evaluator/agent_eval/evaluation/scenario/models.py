"""场景化配置模型 — 数据驱动的聚合策略与指标定义。

对齐 04 评估引擎设计 §七之二、13 配置管理设计 §十。用 AggregationPolicy 替代
ScoreAggregator 中写死的 format/commonsense/quality 阶段与权重；用 MetricDefinition
替代 MetricsCalculator 中写死的 DR/CPR/Reward/CondR 指标。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from agent_eval.core.types import ConstraintTier


class StageWeight(BaseModel):
    """单个阶段在 Reward 聚合中的权重声明。

    evaluator_weights 为空时按门控语义计分（全过=1，任一失败/跳过=0），
    复刻 courseware 的 format/commonsense；非空时按约束加权平均计分，
    复刻 courseware 的 quality(soft/pref)。

    注：evaluator_weights 挂在 StageWeight 而非 policy 级，以允许同一物理阶段
    （如 quality）被拆成 soft / pref 两个加权项——这是与旧 ScoreAggregator 在
    courseware 规则集上输出一致的关键（见 ScenarioScoreAggregator）。
    """

    stage_id: str = Field(description="阶段 ID，对应 RuleSet.cascade.stage 与 StageResult.stage_id")
    weight: float = Field(default=1.0, ge=0.0, description="该阶段在 Reward 中的权重")
    is_gate: bool = Field(default=False, description="是否为门控阶段（参与 CondR 类指标）")
    skip_tiers_in_reward: list[ConstraintTier] = Field(
        default_factory=list,
        description="该阶段不计入 Reward 的 tier（如 quality 阶段跳过 hard_gate/hard_score）",
    )
    evaluator_weights: dict[str, float] = Field(
        default_factory=dict,
        description=(
            "阶段内约束加权映射 {constraint_id: weight}；空 → 门控语义。"
            "键为 ConstraintResult.constraint_id（courseware 下即评估器 ID）"
        ),
    )
    id: str | None = Field(
        default=None,
        description="若设置，该阶段得分以 id 为键暴露到样本级 metrics（如 soft/pref）",
    )

    model_config = {"extra": "allow", "use_enum_values": False}


class AggregationPolicy(BaseModel):
    """评分聚合策略 — 描述如何把阶段结果聚合为 Reward。"""

    id: str = Field(description="策略唯一标识，如 courseware-default")
    scenario_id: str = Field(default="", description="所属场景 ID")
    stage_weights: list[StageWeight] = Field(
        default_factory=list,
        description="阶段权重列表；顺序无关，按 stage_id 匹配 SampleResult.stage_results",
    )
    normalize_to: tuple[float, float] = Field(
        default=(0.0, 1.0),
        description="Reward 归一化区间；courseware 为 [0,1]",
    )

    model_config = {"extra": "allow"}


class MetricDefinition(BaseModel):
    """指标定义 — 用安全表达式声明一个运行级指标。"""

    id: str = Field(description="指标唯一标识，如 courseware:document_rate")
    name: str = Field(default="", description="指标展示名")
    expression: str = Field(
        description=(
            "安全表达式。可用：total；样本过程字段数组（reward/total_duration_ms/llm_calls/token_usage）；"
            "场景化样本指标数组（SampleResult.stage_metrics 的 key，如 soft/pref）；"
            "<stage_id>_gate（该阶段门控通过布尔数组）；"
            "函数 mean/count/sum/min/max/len/abs/both/all/any/gated_mean"
        ),
    )
    threshold: float | None = Field(default=None, description="通过阈值（可选）")
    unit: str | None = Field(default=None, description="单位：ratio/score/ms/count")
    summary: str | None = Field(
        default=None, description="一句话大白话描述指标含义，用于摘要报告展示（非技术用户可读）"
    )
    explain: dict | None = Field(
        default=None,
        description=(
            "可选指标说明（前端 ? hover 提示）：{title, rows:[{dt, dd, tone?}]}，"
            "tone ∈ default/primary/danger/success/warning 控制强调色"
        ),
    )

    model_config = {"extra": "allow"}


class ScenarioConfig(BaseModel):
    """场景配置 — 绑定一个场景的默认聚合策略与指标集。"""

    scenario_id: str = Field(description="场景 ID")
    aggregation_policy: AggregationPolicy = Field(description="默认聚合策略")
    metric_definitions: list[MetricDefinition] = Field(
        default_factory=list, description="默认指标定义列表"
    )

    model_config = {"extra": "allow"}
