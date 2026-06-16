"""规则 SDK — 编程式规则管理接口。

提供创建、修改、校验、提交规则集的能力，便于在 Python 脚本或 Agent 中
程序化地维护评估规则。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_eval.config.loader import ConfigLoader
from agent_eval.rules.manager import RuleSetManager
from agent_eval.rules.models import (
    CascadeStage,
    Dimension,
    Rule,
    RuleSet,
    RuleSetMeta,
)
from agent_eval.rules.template import TemplateResolver
from agent_eval.rules.validation import RuleSetValidator


class RuleSDK:
    """规则集编程式管理 SDK。"""

    def __init__(self, rule_set_path: Path | str) -> None:
        self.rule_set_path = Path(rule_set_path)
        self.manager = RuleSetManager(self.rule_set_path)
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

    # ─── 加载与提交 ───

    def load(self, *, resolve_templates: bool = True) -> RuleSet:
        """从磁盘加载 RuleSet。"""
        return self.manager.load(resolve_templates=resolve_templates)

    def commit(self, rule_set: RuleSet, message: str = "") -> str:
        """校验并保存 RuleSet 到磁盘（自动归档旧版本）。

        Returns:
            保存后的版本号。
        """
        errors = self.validate(rule_set)
        if errors:
            raise ValueError(f"RuleSet 语义校验失败: {errors}")
        return self.manager.apply(rule_set, commit_message=message)

    def diff(self, rule_set: RuleSet) -> Any:
        """对比给定 RuleSet 与磁盘当前版本。"""
        current = self.load(resolve_templates=False)
        return self.manager._compute_diff(current, rule_set)

    def bump_version(
        self,
        change_type: str = "patch",
        description: str = "",
    ) -> str:
        """递增磁盘上 RuleSet 的版本号。"""
        return self.manager.bump_version(change_type, description)
