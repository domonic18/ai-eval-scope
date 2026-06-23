"""规则 SDK — 编程式规则管理接口。

提供创建、修改、校验、模板解析规则集的能力，便于在 Python 脚本或 Agent 中
程序化地维护评估规则。

注：规则集版本管理（提交/差异/回滚）已迁移至 git，本 SDK 不再承担版本管理职责。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_eval.config.loader import ConfigLoader
from agent_eval.rules.models import (
    CascadeStage,
    Dimension,
    Rule,
    RuleSet,
)
from agent_eval.rules.template import TemplateResolver
from agent_eval.rules.validation import RuleSetValidator


class RuleSDK:
    """规则集编程式管理 SDK。"""

    def __init__(self, rule_set_path: Path | str) -> None:
        self.rule_set_path = Path(rule_set_path)
        self.validator = RuleSetValidator()

    # ─── 创建 ───

    @staticmethod
    def create(
        version: str = "1.0.0",
        description: str = "",
        *,
        dimensions: list[dict[str, Any]] | None = None,
        cascade: list[dict[str, Any]] | None = None,
        rules: list[dict[str, Any]] | None = None,
        templates: list[dict[str, Any]] | None = None,
    ) -> RuleSet:
        """从零创建一个新的 RuleSet。"""
        data: dict[str, Any] = {
            "version": version,
            "description": description,
            "meta": {
                "version": version,
                "description": description,
            },
            "dimensions": dimensions or [],
            "cascade": cascade or [],
            "rules": rules or [],
            "templates": templates or [],
        }
        return RuleSet.model_validate(data)

    # ─── 修改 ───

    @staticmethod
    def add_rule(
        rule_set: RuleSet,
        rule: Rule | dict[str, Any],
    ) -> RuleSet:
        """向 RuleSet 添加一条规则（返回同一实例，支持链式调用）。"""
        if isinstance(rule, dict):
            rule = Rule.model_validate(rule)
        rule_set.rules.append(rule)
        return rule_set

    @staticmethod
    def add_dimension(
        rule_set: RuleSet,
        dimension: Dimension | dict[str, Any],
    ) -> RuleSet:
        """向 RuleSet 添加一个维度。"""
        if isinstance(dimension, dict):
            dimension = Dimension.model_validate(dimension)
        rule_set.dimensions.append(dimension)
        return rule_set

    @staticmethod
    def add_cascade_stage(
        rule_set: RuleSet,
        stage: CascadeStage | dict[str, Any],
    ) -> RuleSet:
        """向 RuleSet 添加一个级联阶段。"""
        if isinstance(stage, dict):
            stage = CascadeStage.model_validate(stage)
        rule_set.cascade.append(stage)
        return rule_set

    @staticmethod
    def enable_rule(rule_set: RuleSet, rule_id: str, enabled: bool = True) -> RuleSet:
        """启用/禁用指定规则。"""
        rule = rule_set.get_rule(rule_id)
        if rule is None:
            raise ValueError(f"规则不存在: {rule_id}")
        rule.enabled = enabled
        return rule_set

    # ─── 校验 ───

    def validate(self, rule_set: RuleSet) -> list[str]:
        """语义校验 RuleSet，返回错误列表（空表示通过）。"""
        return self.validator.validate(rule_set)

    @staticmethod
    def resolve_templates(rule_set: RuleSet) -> RuleSet:
        """解析 RuleSet 中的模板引用，返回物化后的 RuleSet。"""
        if not rule_set.templates:
            return rule_set
        return TemplateResolver(rule_set).resolve()

    # ─── 加载 ───

    def load(self, *, resolve_templates: bool = True) -> RuleSet:
        """从磁盘加载 RuleSet。"""
        return ConfigLoader.load_rule_set(self.rule_set_path, resolve_templates=resolve_templates)
