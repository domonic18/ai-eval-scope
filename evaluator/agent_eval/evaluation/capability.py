"""能力派生解析 — 从规则集派生评估所需的基础设施能力（docs/arch/13）。

单一事实源：能力需求声明在评估器定义处（BaseEvaluator.requires / method 默认映射），
本模块扫描规则集的 enabled 规则，聚合出所需能力集合，供 orchestrator 自动供给。

>>> from agent_eval.evaluation.capability import CapabilityResolver
>>> req = CapabilityResolver(registry).resolve(rule_set)
>>> Capability.LLM in req.capabilities
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from agent_eval.core.types import Capability

if TYPE_CHECKING:
    from agent_eval.evaluation.registry import EvaluatorRegistry


@dataclass(frozen=True)
class RequiredCapabilities:
    """规则集派生出的能力需求快照。"""

    capabilities: frozenset[Capability]
    # 审计/报错可读：每个评估器 → 其所需能力（仅含 enabled 规则引用的评估器）
    by_evaluator: dict[str, frozenset[Capability]] = field(default_factory=dict)

    @classmethod
    def empty(cls) -> RequiredCapabilities:
        return cls(capabilities=frozenset(), by_evaluator={})


class CapabilityResolver:
    """扫描规则集 → 聚合 enabled 规则所引用评估器的能力需求。"""

    def __init__(self, registry: EvaluatorRegistry) -> None:
        self._registry = registry

    def resolve(self, rule_set: Any | None) -> RequiredCapabilities:
        """派生规则集所需能力。

        - rule_set 为 None（纯格式评估）→ 空集。
        - 仅扫描 enabled 规则（enabled=false 的规则不产生需求，见 [04] §5.6）。
        - 未注册的评估器 id 忽略（不阻断，由管线侧另行报错）。
        """
        if rule_set is None:
            return RequiredCapabilities.empty()

        rules = getattr(rule_set, "rules", []) or []
        by_evaluator: dict[str, frozenset[Capability]] = {}
        caps: set[Capability] = set()
        for rule in rules:
            if not getattr(rule, "enabled", True):
                continue
            evaluator_id = getattr(rule, "evaluator", "")
            if not evaluator_id or evaluator_id in by_evaluator:
                continue
            cls = self._registry.get_evaluator_class(evaluator_id)
            if cls is None:
                continue  # 未注册评估器由 engine 侧报 EvaluatorNotFoundError
            rule_caps = cls.capabilities()
            by_evaluator[evaluator_id] = rule_caps
            caps.update(rule_caps)
        return RequiredCapabilities(capabilities=frozenset(caps), by_evaluator=by_evaluator)
