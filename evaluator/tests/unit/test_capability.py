"""CapabilityResolver 单测 — 规则集派生能力需求。"""

from __future__ import annotations

from unittest.mock import MagicMock

from agent_eval.core.types import Capability, EvalMethod
from agent_eval.evaluation.base import BaseEvaluator
from agent_eval.evaluation.capability import CapabilityResolver, RequiredCapabilities
from agent_eval.evaluation.registry import EvaluatorRegistry


def _rule(evaluator: str, enabled: bool = True) -> MagicMock:
    r = MagicMock()
    r.evaluator = evaluator
    r.enabled = enabled
    return r


def _ruleset(rules: list[MagicMock]) -> MagicMock:
    rs = MagicMock()
    rs.rules = rules
    return rs


def _registry_with(*evaluators: type[BaseEvaluator]) -> EvaluatorRegistry:
    reg = EvaluatorRegistry()
    for ev in evaluators:
        # 复用真实注册路径：用 evaluator_id 注册
        reg._registry[ev.evaluator_id] = ev  # type: ignore[attr-defined]
    return reg


class _RuleEvaluator(BaseEvaluator):
    evaluator_id = "t.rule"
    method = EvalMethod.RULE

    def evaluate(self, sample, context):  # type: ignore[no-untyped-def]
        ...


class _LLmEvaluator(BaseEvaluator):
    evaluator_id = "t.llm"
    method = EvalMethod.LLM_JUDGE

    def evaluate(self, sample, context):  # type: ignore[no-untyped-def]
        ...


class _VisionEvaluator(BaseEvaluator):
    evaluator_id = "t.vision"
    method = EvalMethod.VISION

    def evaluate(self, sample, context):  # type: ignore[no-untyped-def]
        ...


def test_resolve_none_ruleset_returns_empty() -> None:
    reg = _registry_with(_LLmEvaluator)
    req = CapabilityResolver(reg).resolve(None)
    assert req.capabilities == frozenset()


def test_resolve_aggregates_capabilities_from_enabled_rules() -> None:
    reg = _registry_with(_RuleEvaluator, _LLmEvaluator, _VisionEvaluator)
    rs = _ruleset([_rule("t.rule"), _rule("t.llm"), _rule("t.vision")])
    req = CapabilityResolver(reg).resolve(rs)
    assert Capability.LLM in req.capabilities
    assert Capability.VISION in req.capabilities
    # by_evaluator 审计字段
    assert req.by_evaluator["t.llm"] == frozenset({Capability.LLM})
    assert req.by_evaluator["t.vision"] == frozenset({Capability.LLM, Capability.VISION})


def test_resolve_ignores_disabled_rules() -> None:
    reg = _registry_with(_LLmEvaluator)
    rs = _ruleset([_rule("t.llm", enabled=False)])
    req = CapabilityResolver(reg).resolve(rs)
    assert Capability.LLM not in req.capabilities
    assert "t.llm" not in req.by_evaluator


def test_resolve_ignores_unregistered_evaluator() -> None:
    reg = _registry_with(_LLmEvaluator)
    rs = _ruleset([_rule("t.llm"), _rule("does.not.exist")])
    req = CapabilityResolver(reg).resolve(rs)
    assert Capability.LLM in req.capabilities
    assert "does.not.exist" not in req.by_evaluator


def test_resolve_dedupes_repeated_evaluator() -> None:
    reg = _registry_with(_LLmEvaluator)
    rs = _ruleset([_rule("t.llm"), _rule("t.llm")])
    req = CapabilityResolver(reg).resolve(rs)
    assert req.capabilities == frozenset({Capability.LLM})
    assert len(req.by_evaluator) == 1


def test_rule_only_ruleset_needs_nothing() -> None:
    reg = _registry_with(_RuleEvaluator)
    rs = _ruleset([_rule("t.rule")])
    req = CapabilityResolver(reg).resolve(rs)
    assert req.capabilities == frozenset()


def test_empty_singleton() -> None:
    assert RequiredCapabilities.empty().capabilities == frozenset()
