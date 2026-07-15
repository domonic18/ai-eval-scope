"""courseware 默认聚合策略与指标定义 — 从包内 YAML 单一源加载。

配置收敛到 courseware 包内 ``metrics/policy.yaml``（#60），
evaluator Python 与 backend TS 均从此文件读取，消除跨语言重复。
路径经 ``paths.rules_dir.parent`` 动态解析（自动取最高版本，不硬编码版本号）。

等价复刻旧 ScoreAggregator / MetricsCalculator 在课件规则集上的行为（见
tests/unit/test_scenario_aggregation.py）。
"""

from __future__ import annotations

from typing import Any

import yaml

from agent_eval.config.paths import paths
from agent_eval.evaluation.scenario.models import (
    AggregationPolicy,
    MetricDefinition,
    ScenarioConfig,
)

COURSEWARE_SCENARIO_ID = "courseware"


def _policy_yaml_path() -> Any:
    """courseware 包内 metrics/policy.yaml 路径（经 paths 动态解析，不硬编码版本）。"""
    from pathlib import Path

    return Path(paths.rules_dir).parent / "metrics" / "policy.yaml"


def _load_yaml() -> dict[str, Any]:
    """加载 courseware 场景配置 YAML。"""
    yaml_path = _policy_yaml_path()
    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"policy.yaml 须为映射类型: {yaml_path}")
    return data


def _build_default_policy() -> AggregationPolicy:
    """从 YAML 构造 courseware 默认 AggregationPolicy。"""
    return AggregationPolicy.model_validate(_load_yaml()["aggregation_policy"])


def _build_default_metrics() -> list[MetricDefinition]:
    """从 YAML 构造 courseware 默认 MetricDefinition 列表。"""
    raw = _load_yaml()["metric_definitions"]
    return [MetricDefinition.model_validate(item) for item in raw]


COURSEWARE_DEFAULT_POLICY: AggregationPolicy = _build_default_policy()
COURSEWARE_DEFAULT_METRICS: list[MetricDefinition] = _build_default_metrics()

COURSEWARE_SCENARIO_CONFIG: ScenarioConfig = ScenarioConfig(
    scenario_id=COURSEWARE_SCENARIO_ID,
    aggregation_policy=COURSEWARE_DEFAULT_POLICY,
    metric_definitions=COURSEWARE_DEFAULT_METRICS,
)
