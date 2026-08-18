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


def load_scenario_config_from_package(package_dir: Any) -> ScenarioConfig | None:
    """从场景包目录的 metrics/policy.yaml 构造 ScenarioConfig（数据驱动，任意场景）。

    多场景配置加载的统一入口：解析 ``<package_dir>/metrics/policy.yaml`` 的
    aggregation_policy + metric_definitions。缺文件或格式异常 → None（调用方回退 courseware）。
    与 courseware 默认共用同一份 policy.yaml 契约（#60 跨语言单一源）。
    """
    from pathlib import Path

    policy_yaml = Path(package_dir) / "metrics" / "policy.yaml"
    if not policy_yaml.exists():
        return None
    data = yaml.safe_load(policy_yaml.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "aggregation_policy" not in data:
        return None
    scenario_id = data["aggregation_policy"].get("scenario_id") or Path(package_dir).name
    return ScenarioConfig(
        scenario_id=str(scenario_id),
        aggregation_policy=AggregationPolicy.model_validate(data["aggregation_policy"]),
        metric_definitions=[
            MetricDefinition.model_validate(m) for m in data.get("metric_definitions", [])
        ],
    )
