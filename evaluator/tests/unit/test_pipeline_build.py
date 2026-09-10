"""build_pipeline 构建期守卫测试——聚合策略必选、覆盖度 fail-loud 与规则 tier 覆盖。

背景（run 20260910_034232 事故）：规则集阶段未被聚合策略声明时分数被静默丢弃
（safety judge 打 0 分样本仍 reward=1.0）；judge 规则默认 soft 层级，0 分只在
score 上体现、不翻转样本 status。聚合策略不再回退 courseware 默认——缺
metrics/policy.yaml 即构建期打回。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_eval.core.types import ConstraintTier
from agent_eval.evaluation.engine import build_pipeline
from agent_eval.evaluation.evaluators import *  # noqa: F401,F403 — trigger registration
from agent_eval.evaluation.registry import registry
from agent_eval.rules.models import Rule, RuleSet

_WEIGHTS = {
    "format": "    - stage_id: format\n      weight: 1.0\n      is_gate: true\n",
    "safety": (
        "    - stage_id: safety\n      weight: 1.0\n      is_gate: false\n"
        "      skip_tiers_in_reward: []\n      id: safety\n"
        "      evaluator_weights:\n        format.response_format: 1.0\n"
    ),
}


def _rule_set(stage: str, tier: str | None = None) -> RuleSet:
    kwargs: dict[str, object] = {
        "method": "format",
        "format_type": "extension",
        "extensions": ["md"],
    }
    if tier is not None:
        kwargs["tier"] = tier
    return RuleSet(rules=[Rule(id="R1", stage=stage, evaluator="format.response_format", **kwargs)])


def _write_policy(tmp_path: Path, *stages: str) -> Path:
    """写含指定 stage_weights 的 policy.yaml，返回包根。"""
    (tmp_path / "metrics").mkdir(exist_ok=True)
    body = "".join(_WEIGHTS[s] for s in stages)
    (tmp_path / "metrics" / "policy.yaml").write_text(
        "aggregation_policy:\n"
        "  id: t\n"
        "  scenario_id: t\n"
        "  stage_weights:\n"
        f"{body}"
        "  normalize_to: [0.0, 1.0]\n",
        encoding="utf-8",
    )
    return tmp_path


def test_missing_policy_yaml_raises() -> None:
    """无场景包（缺 metrics/policy.yaml）→ 构建期打回，不再回退 courseware 默认。"""
    from agent_eval.core.exceptions import ScenarioError

    with pytest.raises(ScenarioError, match="policy.yaml"):
        build_pipeline(registry, _rule_set("format"))


def test_stage_coverage_missing_raises(tmp_path: Path) -> None:
    """policy 只声明 format，规则集出现 safety 阶段 → 构建期打回（此前静默丢分）。"""
    from agent_eval.core.exceptions import ScenarioError

    pkg = _write_policy(tmp_path, "format")
    with pytest.raises(ScenarioError, match="safety"):
        build_pipeline(registry, _rule_set("safety"), package_dir=pkg)


def test_stage_coverage_declared_in_package_policy_passes(tmp_path: Path) -> None:
    """包内 policy.yaml 声明了全部规则阶段 → 构建通过。"""
    pkg = _write_policy(tmp_path, "safety")
    engine = build_pipeline(registry, _rule_set("safety"), package_dir=pkg)
    assert [s.stage_id for s in engine.stages] == ["safety"]


def test_rule_tier_overrides_evaluator_default(tmp_path: Path) -> None:
    """规则声明 tier 覆盖评估器内置层级（实例属性，不污染其他实例）。"""
    pkg = _write_policy(tmp_path, "format")
    engine = build_pipeline(registry, _rule_set("format", tier="soft"), package_dir=pkg)
    evaluator = engine.stages[0].evaluators[0]
    assert evaluator.tier == ConstraintTier.SOFT
    fresh = registry.create(
        "format.response_format", {"format_type": "extension", "extensions": ["md"]}
    )
    assert fresh.tier == ConstraintTier.HARD_GATE  # 类属性不受实例覆盖影响


def test_rule_tier_invalid_value_rejected() -> None:
    with pytest.raises(ValueError, match="tier"):
        _rule_set("format", tier="ultra")
