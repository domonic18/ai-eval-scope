"""规则侧数据模型。

定义规则集（RuleSet）、规则（Rule）、维度（Dimension）、级联阶段（CascadeStage）、
规则模板（RuleTemplate）以及版本管理相关模型。
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, model_validator


class RuleMethod(str, Enum):
    """规则层声明的评估方式 —— 决定 UI 渲染与执行器绑定。"""

    LLM = "llm"
    LLM_VISION = "llm_vision"
    RULE_SET = "rule_set"
    FORMAT = "format"


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
    # 场景包标识（Phase 0 新增，对齐 13 配置管理设计 §3.1）
    scenario_id: str | None = Field(
        default=None, description="所属场景 ID（命名空间），如 courseware"
    )
    package_id: str | None = Field(default=None, description="所属场景包 ID")
    name: str = Field(description="模板名称")
    description: str = Field(default="", description="模板描述")
    dimension: str = Field(description="默认维度 ID")
    stage: str = Field(description="默认级联阶段 ID")
    method: RuleMethod = Field(description="评估方式：llm / llm_vision / rule_set / format")
    prompt_id: str | None = Field(
        default=None,
        description="LLM/视觉评估的主提示词 ID；rule_set 复合评估（如 info_accuracy）也可绑定",
    )
    confirmation_prompt_id: str | None = Field(
        default=None,
        description="rule_set 复合评估的二次确认提示词 ID（如 fact_verdict）；仅 rule_set 可用",
    )
    dataset_ids: list[str] | None = Field(
        default=None,
        description="规则集评估关联的参考数据集 ID 列表；空/None=使用全部参考数据集（知识库）",
    )
    format_type: str | None = Field(
        default=None,
        description="格式检查子类型：extension / json_validity / html_validity / markdown / content_completeness",
    )
    extensions: list[str] | None = Field(
        default=None, description="format_type=extension 时允许的后缀列表"
    )
    evaluator: str | None = Field(
        default=None, description="具体执行器标识；省略时由 method + 绑定资产派生"
    )
    params: dict[str, Any] = Field(default_factory=dict, description="默认参数")
    weight: float = Field(default=1.0, ge=0.0, description="默认权重")

    model_config = {"extra": "allow"}

    @model_validator(mode="after")
    def _check_bindings(self) -> RuleTemplate:
        method = self.method
        if method in (RuleMethod.LLM, RuleMethod.LLM_VISION):
            if not self.prompt_id:
                raise ValueError(f"method={method.value} 时必须提供 prompt_id")
            if self.dataset_ids is not None or self.confirmation_prompt_id is not None:
                raise ValueError(
                    f"method={method.value} 不允许 dataset_ids / confirmation_prompt_id"
                )
        elif method == RuleMethod.RULE_SET:
            # dataset_ids 可选（空=全部知识库）；prompt_id / confirmation_prompt_id 可选（评估器有默认）
            if self.format_type is not None or self.extensions is not None:
                raise ValueError("method=rule_set 不允许 format_type / extensions")
        elif method == RuleMethod.FORMAT:
            if not self.format_type:
                raise ValueError("method=format 时必须提供 format_type")
            if self.format_type == "extension" and not self.extensions:
                raise ValueError("format_type=extension 时必须提供 extensions")
            if self.prompt_id or self.dataset_ids is not None or self.confirmation_prompt_id:
                raise ValueError(
                    "method=format 不允许 prompt_id / dataset_ids / confirmation_prompt_id"
                )
        return self


class Rule(BaseModel):
    """单条评估规则 — 绑定评估器、参数和惩罚策略。

    支持两种定义方式：
    1. 内联定义：直接填写所有字段；
    2. 模板继承：通过 template_ref 引用 RuleTemplate，再使用 overrides
       覆盖模板中的字段。
    """

    id: str = Field(description="规则 ID，如 FMT_001")
    # 场景包标识（Phase 0 新增，对齐 13 配置管理设计 §3.1）
    scenario_id: str | None = Field(
        default=None, description="所属场景 ID（命名空间），如 courseware"
    )
    package_id: str | None = Field(default=None, description="所属场景包 ID")
    name: str = Field(default="", description="规则名称，如 输出格式有效")
    dimension: str = Field(default="", description="所属维度 ID")
    stage: str = Field(default="", description="所属级联阶段 ID")
    description: str = Field(default="", description="规则描述")
    method: RuleMethod | None = Field(
        default=None,
        description="评估方式：llm / llm_vision / rule_set / format；使用 template_ref 时可缺省（继承自模板）",
    )
    prompt_id: str | None = Field(
        default=None,
        description="LLM/视觉评估的主提示词 ID；rule_set 复合评估（如 info_accuracy）也可绑定",
    )
    confirmation_prompt_id: str | None = Field(
        default=None,
        description="rule_set 复合评估的二次确认提示词 ID（如 fact_verdict）；仅 rule_set 可用",
    )
    dataset_ids: list[str] | None = Field(
        default=None,
        description="规则集评估关联的参考数据集 ID 列表；空/None=使用全部参考数据集（知识库）",
    )
    format_type: str | None = Field(
        default=None,
        description="格式检查子类型：extension / json_validity / html_validity / markdown / content_completeness",
    )
    extensions: list[str] | None = Field(
        default=None, description="format_type=extension 时允许的后缀列表"
    )
    evaluator: str | None = Field(
        default=None, description="具体执行器标识；省略时由 method + 绑定资产派生"
    )
    params: dict[str, Any] = Field(default_factory=dict, description="评估器参数")
    weight: float = Field(default=1.0, ge=0.0, description="规则权重")
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

    @model_validator(mode="after")
    def _check_bindings(self) -> Rule:
        # 模板继承：method/bindings 在解析阶段从模板继承，原始规则可缺省
        if self.template_ref is not None:
            return self
        method = self.method
        if method is None:
            raise ValueError("method 未设置（llm / llm_vision / rule_set / format）")
        if method in (RuleMethod.LLM, RuleMethod.LLM_VISION):
            if not self.prompt_id:
                raise ValueError(f"method={method.value} 时必须提供 prompt_id")
            if self.dataset_ids is not None or self.confirmation_prompt_id is not None:
                raise ValueError(
                    f"method={method.value} 不允许 dataset_ids / confirmation_prompt_id"
                )
        elif method == RuleMethod.RULE_SET:
            # dataset_ids 可选（空=全部知识库）；prompt_id / confirmation_prompt_id 可选（评估器有默认）
            if self.format_type is not None or self.extensions is not None:
                raise ValueError("method=rule_set 不允许 format_type / extensions")
        elif method == RuleMethod.FORMAT:
            if not self.format_type:
                raise ValueError("method=format 时必须提供 format_type")
            if self.format_type == "extension" and not self.extensions:
                raise ValueError("format_type=extension 时必须提供 extensions")
            if self.prompt_id or self.dataset_ids is not None or self.confirmation_prompt_id:
                raise ValueError(
                    "method=format 不允许 prompt_id / dataset_ids / confirmation_prompt_id"
                )
        return self


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
    # 场景包标识（Phase 0 新增，对齐 13 配置管理设计 §3.1）
    # YAML 中以 `scenario:` 键承载场景 ID，Python 侧统一用 scenario_id
    scenario_id: str | None = Field(
        default=None,
        alias="scenario",
        description="所属场景 ID（命名空间），如 courseware",
    )
    package_id: str | None = Field(default=None, description="所属场景包 ID，如 courseware-quality")
    # Phase 1 新增（对齐 04 §7'.2/§10.4）：声明该规则集使用的聚合策略 ID；
    # 未声明时自动套用 courseware 默认策略（scenario_id=courseware）。
    aggregation_policy_id: str | None = Field(
        default=None, description="聚合策略 ID，如 courseware-default；None → 场景默认策略"
    )
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
