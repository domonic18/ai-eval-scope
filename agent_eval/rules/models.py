"""规则侧数据模型。

定义规则集（RuleSet）、规则（Rule）、维度（Dimension）、级联阶段（CascadeStage）。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class Dimension(BaseModel):
    """评估维度 — 如功能性、效果性、安全性等。"""

    id: str = Field(description="维度唯一标识，如 functional")
    name: str = Field(description="维度名称，如 功能性")
    weight: float = Field(default=1.0, ge=0.0, description="维度权重")


class CascadeStage(BaseModel):
    """级联阶段定义。"""

    stage: str = Field(description="阶段标识，如 format_gate")
    name: str = Field(default="", description="阶段名称，如 格式门控")
    stop_on_fail: bool = Field(
        default=False,
        description="阶段内任一规则失败时是否停止后续阶段",
    )


class Rule(BaseModel):
    """单条评估规则 — 绑定评估器、参数和惩罚策略。"""

    id: str = Field(description="规则 ID，如 FMT_001")
    name: str = Field(description="规则名称，如 输出格式有效")
    dimension: str = Field(description="所属维度 ID")
    stage: str = Field(description="所属级联阶段 ID")
    description: str = Field(default="", description="规则描述")
    evaluator: str = Field(description="评估器标识，如 format.response_format")
    params: dict[str, Any] = Field(default_factory=dict, description="评估器参数")
    weight: float = Field(default=1.0, ge=0.0, description="规则权重")
    penalty_on_fail: float | None = Field(
        default=None,
        description="失败惩罚分值（如 -3）",
    )

    model_config = {"extra": "allow"}


class RuleSet(BaseModel):
    """规则集 — 评估场景的完整规则定义。"""

    version: str = Field(description="规则集版本号")
    description: str = Field(default="", description="规则集描述")
    schema_ref: str | None = Field(
        default=None,
        alias="schema",
        description="JSON Schema 引用路径",
    )
    dimensions: list[Dimension] = Field(default_factory=list, description="维度列表")
    cascade: list[CascadeStage] = Field(default_factory=list, description="级联阶段定义")
    rules: list[Rule] = Field(default_factory=list, description="规则列表")

    model_config = {"extra": "allow", "populate_by_name": True}

    def get_rules_by_stage(self, stage_id: str) -> list[Rule]:
        """获取指定阶段的所有规则。"""
        return [r for r in self.rules if r.stage == stage_id]

    def get_cascade_stage(self, stage_id: str) -> CascadeStage | None:
        """获取指定级联阶段定义。"""
        for cs in self.cascade:
            if cs.stage == stage_id:
                return cs
        return None

    def get_rule(self, rule_id: str) -> Rule | None:
        """按 ID 获取规则。"""
        for r in self.rules:
            if r.id == rule_id:
                return r
        return None
