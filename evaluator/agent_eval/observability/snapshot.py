"""运行配置快照（RunConfigSnapshot）构建 — 对齐 13 配置管理设计 §12.1。

每次评估运行生成不可变快照，记录实际使用的规则集/聚合策略/指标定义等，
保证运行可复现、可追溯。快照经 ResultSink 摄取后落入 Web 的 run_config_snapshots 表。
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from agent_eval.evaluation.scenario import (
    COURSEWARE_SCENARIO_CONFIG,
    COURSEWARE_SCENARIO_ID,
)
from agent_eval.evaluation.scenario.models import ScenarioConfig
from agent_eval.rules.models import RuleSet


def _sha256(obj: Any) -> str:
    """对象 → 稳定 SHA-256（canonical JSON）。"""
    return (
        "sha256:"
        + hashlib.sha256(
            json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
        ).hexdigest()
    )


def build_run_config_snapshot(
    rule_set: RuleSet | None = None,
    *,
    scenario_config: ScenarioConfig | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    """构建 RunConfigSnapshot 内容（未含 snapshot_hash 的纯内容）。

    Args:
        rule_set: 本次运行使用的规则集（取 scenario_id/version/content_hash）。
        scenario_config: 场景配置（聚合策略 + 指标定义）；缺省用 courseware 默认。
        run_id: 运行 ID（仅用于溯源，不参与 hash）。
    """
    cfg = scenario_config or COURSEWARE_SCENARIO_CONFIG
    scenario_id = (
        (rule_set.scenario_id if rule_set else None) or cfg.scenario_id or COURSEWARE_SCENARIO_ID
    )

    rule_set_entry: dict[str, Any] | None = None
    if rule_set is not None:
        rs_content = rule_set.model_dump(by_alias=True, exclude_none=True)
        rule_set_entry = {
            "version": rule_set.version,
            "scenario_id": rule_set.scenario_id or scenario_id,
            "content_hash": _sha256(rs_content),
        }

    return {
        "scenario_id": scenario_id,
        "run_id": run_id,
        "package": {"id": scenario_id, "version": "1.0.0"},
        "rule_set": rule_set_entry,
        "aggregation_policy": cfg.aggregation_policy.model_dump(),
        "metric_definitions": [m.model_dump() for m in cfg.metric_definitions],
        # prompts/datasets/evaluator_manifest/sut_config 在 Phase 5 后续随包系统完善
        "prompts": [],
        "datasets": [],
        "evaluator_manifest": {},
    }


def build_snapshot_with_hash(
    rule_set: RuleSet | None = None,
    *,
    scenario_config: ScenarioConfig | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    """构建带 snapshot_hash 的完整快照（hash 覆盖除 run_id 外的内容）。"""
    content = build_run_config_snapshot(rule_set, scenario_config=scenario_config, run_id=run_id)
    hash_payload = {k: v for k, v in content.items() if k != "run_id"}
    content["snapshot_hash"] = _sha256(hash_payload)
    return content
