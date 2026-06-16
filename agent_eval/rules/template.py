"""规则模板解析器。

将 RuleSet 中通过 template_ref 引用模板的规则物化为完整规则。
"""

from __future__ import annotations

from typing import Any

from agent_eval.rules.models import Rule, RuleSet, RuleTemplate


class TemplateResolver:
    """解析 RuleSet 中的模板引用，返回所有规则均已物化的 RuleSet。"""

    def __init__(self, rule_set: RuleSet) -> None:
        self.rule_set = rule_set
        self._template_index: dict[str, RuleTemplate] = {t.id: t for t in rule_set.templates}

    def resolve(self) -> RuleSet:
        """返回新的 RuleSet，其中所有 template_ref 规则均已展开为完整 Rule。"""
        if not self._template_index:
            return self.rule_set

        resolved_rules: list[Rule] = []
        for rule in self.rule_set.rules:
            resolved_rules.append(self.resolve_rule(rule))

        # 构造新 RuleSet：保留模板定义，但规则已物化
        data = self.rule_set.model_dump(by_alias=True, exclude_none=True)
        data["rules"] = [r.model_dump() for r in resolved_rules]
        return RuleSet.model_validate(data)

    def resolve_rule(self, rule: Rule) -> Rule:
        """物化单条规则：template 默认值 → rule 显式字段 → overrides。"""
        if rule.template_ref is None:
            return rule

        template = self._template_index.get(rule.template_ref)
        if template is None:
            raise ValueError(f"规则 '{rule.id}' 引用的模板 '{rule.template_ref}' 不存在")

        merged = self._merge_fields(template, rule)
        return Rule.model_validate(merged)

    @staticmethod
    def _merge_fields(template: RuleTemplate, rule: Rule) -> dict[str, Any]:
        """三向合并：模板默认值 + 规则显式字段 + overrides。

        规则中未设置（空字符串/空列表/空字典/None）的字段不覆盖模板默认值，
        显式设置的字段优先级高于模板，overrides 优先级最高。
        """
        base = template.model_dump()
        explicit = rule.model_dump(exclude={"template_ref", "overrides", "enabled", "metadata"})
        # 过滤掉未显式设置的值，避免覆盖模板默认值
        explicit = {k: v for k, v in explicit.items() if _is_explicitly_set(v)}

        merged: dict[str, Any] = {**base, **explicit}
        merged.update(rule.overrides)

        # 以下字段永远以规则本身为准
        merged["id"] = rule.id
        merged["template_ref"] = rule.template_ref
        merged["enabled"] = rule.enabled
        if rule.metadata:
            merged.setdefault("metadata", {}).update(rule.metadata)

        return merged


def _is_explicitly_set(value: Any) -> bool:
    """判断字段是否被显式设置。"""
    if value is None:
        return False
    if value == "":
        return False
    if isinstance(value, list | dict | set) and not value:
        return False
    return True
