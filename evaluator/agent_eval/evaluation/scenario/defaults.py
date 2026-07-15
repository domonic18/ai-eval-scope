"""courseware 默认聚合策略与指标定义 — 从包内 YAML 单一源加载。

配置收敛到 ``assets/packages/courseware/1.0.0/metrics/policy.yaml``（#60），
evaluator Python 与 backend TS 均从此文件读取，消除跨语言重复。

等价复刻旧 ScoreAggregator / MetricsCalculator 在课件规则集上的行为（见
tests/unit/test_scenario_aggregation.py）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from agent_eval.evaluation.scenario.models import (
    AggregationPolicy,
    MetricDefinition,
    ScenarioConfig,
)

COURSEWARE_SCENARIO_ID = "courseware"

_YAML_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "assets"
    / "packages"
    / "courseware"
    / "1.0.0"
    / "metrics"
    / "policy.yaml"
)


def _load_yaml() -> dict[str, Any]:
    """加载 courseware 场景配置 YAML。"""
    data = yaml.safe_load(_YAML_PATH.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"policy.yaml 须为映射类型: {_YAML_PATH}")
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
