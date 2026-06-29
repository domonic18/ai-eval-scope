"""规则侧数据模型。

定义规则集（RuleSet）、规则（Rule）、维度（Dimension）、级联阶段（CascadeStage）、
规则模板（RuleTemplate）以及版本管理相关模型。
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


class RuleTemplate(BaseModel):
    """规则模板 — 可复用的规则蓝图，可被规则引用并覆盖部分字段。"""

    id: str = Field(description="模板唯一标识")
    name: str = Field(description="模板名称")
    description: str = Field(default="", description="模板描述")
    dimension: str = Field(description="默认维度 ID")
    stage: str = Field(description="默认级联阶段 ID")
    evaluator: str = Field(description="默认评估器标识")
    params: dict[str, Any] = Field(default_factory=dict, description="默认参数")
    weight: float = Field(default=1.0, ge=0.0, description="默认权重")
    penalty_on_fail: float | None = Field(
        default=None,
        description="失败惩罚分值（如 -3）",
    )

    model_config = {"extra": "allow"}


class Rule(BaseModel):
    """单条评估规则 — 绑定评估器、参数和惩罚策略。

    支持两种定义方式：
    1. 内联定义：直接填写所有字段；
    2. 模板继承：通过 template_ref 引用 RuleTemplate，再使用 overrides
       覆盖模板中的字段。
    """

    id: str = Field(description="规则 ID，如 FMT_001")
    name: str = Field(default="", description="规则名称，如 输出格式有效")
    dimension: str = Field(default="", description="所属维度 ID")
    stage: str = Field(default="", description="所属级联阶段 ID")
    description: str = Field(default="", description="规则描述")
    evaluator: str = Field(default="", description="评估器标识，如 format.response_format")
    params: dict[str, Any] = Field(default_factory=dict, description="评估器参数")
    weight: float = Field(default=1.0, ge=0.0, description="规则权重")
    penalty_on_fail: float | None = Field(
        default=None,
        description="失败惩罚分值（如 -3）",
    )
    # 模板继承相关
    template_ref: str | None = Field(
        default=None,
        description="引用的模板 ID；设置时未显式覆盖的字段取自模板",
    )
    overrides: dict[str, Any] = Field(
        default_factory=dict,
        description="对模板字段的覆盖值",
    )
    enabled: bool = Field(default=True, description="是否启用该规则")
    metadata: dict[str, Any] = Field(default_factory=dict, description="规则元数据")

    model_config = {"extra": "allow"}


class RuleSetMeta(BaseModel):
    """规则集元数据与版本信息。"""

    version: str = Field(default="1.0.0", description="语义版本号")
    description: str = Field(default="", description="规则集描述")
    author: str = Field(default="", description="作者")
    created_at: str = Field(default="", description="创建时间 ISO 8601")
    updated_at: str = Field(default="", description="更新时间 ISO 8601")

    model_config = {"extra": "allow"}


class RuleSet(BaseModel):
    """规则集 — 评估场景的完整规则定义。"""

    version: str = Field(default="1.0.0", description="规则集版本号（与 meta.version 保持一致）")
    description: str = Field(default="", description="规则集描述")
    schema_ref: str | None = Field(
        default=None,
        alias="schema",
        description="JSON Schema 引用路径",
    )
    dimensions: list[Dimension] = Field(default_factory=list, description="维度列表")
    cascade: list[CascadeStage] = Field(default_factory=list, description="级联阶段定义")
    rules: list[Rule] = Field(default_factory=list, description="规则列表")
    # Sprint 7 新增
    meta: RuleSetMeta = Field(default_factory=RuleSetMeta, description="规则集元数据")
    templates: list[RuleTemplate] = Field(
        default_factory=list,
        description="本规则集内联定义的模板",
    )

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

    def get_template(self, template_id: str) -> RuleTemplate | None:
        """按 ID 获取模板。"""
        for t in self.templates:
            if t.id == template_id:
                return t
        return None
