"""规则集语义校验。

在 JSON Schema 结构校验之外，检查 RuleSet 的语义一致性：
- 引用的评估器是否已注册
- 规则引用的 dimension/stage 是否在规则集中定义
- 规则 ID 是否唯一
- 模板引用是否有效
"""

from __future__ import annotations

from agent_eval.evaluation.registry import registry
from agent_eval.rules.models import RuleSet


class RuleSetValidator:
    """RuleSet 语义校验器。"""

    def __init__(self) -> None:
        self._errors: list[str] = []

    def validate(self, rule_set: RuleSet) -> list[str]:
        """执行完整语义校验，返回错误列表（空表示通过）。"""
        self._errors = []
        self._validate_rule_ids_unique(rule_set)
        self._validate_dimensions(rule_set)
        self._validate_stages(rule_set)
        self._validate_template_refs(rule_set)
        self._validate_evaluators(rule_set)
        return self._errors

    def _add_error(self, message: str) -> None:
        self._errors.append(message)

    def _validate_rule_ids_unique(self, rule_set: RuleSet) -> None:
        seen: set[str] = set()
        for rule in rule_set.rules:
            if rule.id in seen:
                self._add_error(f"规则 ID 重复: '{rule.id}'")
            seen.add(rule.id)

    def _validate_dimensions(self, rule_set: RuleSet) -> None:
        dim_ids = {d.id for d in rule_set.dimensions}
        for rule in rule_set.rules:
            if not rule.enabled:
                continue
            if not rule.dimension:
                self._add_error(f"规则 '{rule.id}': dimension 未设置")
            elif rule.dimension not in dim_ids:
                self._add_error(
                    f"规则 '{rule.id}': dimension '{rule.dimension}' 未在 dimensions 中定义"
                )

    def _validate_stages(self, rule_set: RuleSet) -> None:
        stage_ids = {c.stage for c in rule_set.cascade}
        for rule in rule_set.rules:
            if not rule.enabled:
                continue
            if not rule.stage:
                self._add_error(f"规则 '{rule.id}': stage 未设置")
            elif rule.stage not in stage_ids:
                self._add_error(f"规则 '{rule.id}': stage '{rule.stage}' 未在 cascade 中定义")

    def _validate_template_refs(self, rule_set: RuleSet) -> None:
        template_ids = {t.id for t in rule_set.templates}
        for rule in rule_set.rules:
            if rule.template_ref is None:
                continue
            if rule.template_ref not in template_ids:
                self._add_error(
                    f"规则 '{rule.id}': template_ref '{rule.template_ref}' 未在 templates 中定义"
                )

    def _validate_evaluators(self, rule_set: RuleSet) -> None:
        for rule in rule_set.rules:
            if not rule.enabled:
                continue
            # 若规则使用模板且未覆盖 evaluator，则 evaluator 可能为空
            if not rule.evaluator:
                if rule.template_ref is None:
                    self._add_error(f"规则 '{rule.id}': evaluator 未设置")
                continue
            if not registry.is_registered(rule.evaluator):
                self._add_error(
                    f"规则 '{rule.id}': evaluator '{rule.evaluator}' 未注册；"
                    f"已注册评估器: {', '.join(registry.list_registered())}"
                )
