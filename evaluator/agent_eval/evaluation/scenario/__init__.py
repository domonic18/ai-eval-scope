"""场景化聚合与指标（数据驱动）— 对齐 04 评估引擎设计 §七之二、13 配置管理设计 §十。

公开类型：
- ScenarioConfig / AggregationPolicy / StageWeight / MetricDefinition：配置模型
- ScenarioScoreAggregator：按策略聚合样本级 reward（替代旧 ScoreAggregator 硬编码）
- ScenarioMetricsCalculator：按声明计算运行级指标（替代旧 MetricsCalculator 硬编码）
- COURSEWARE_*：courseware 默认策略/指标，等价复刻旧实现
"""

from __future__ import annotations

from agent_eval.evaluation.scenario.aggregator import ScenarioScoreAggregator
from agent_eval.evaluation.scenario.defaults import (
    COURSEWARE_DEFAULT_METRICS,
    COURSEWARE_DEFAULT_POLICY,
    COURSEWARE_SCENARIO_CONFIG,
    COURSEWARE_SCENARIO_ID,
)
from agent_eval.evaluation.scenario.expr import safe_eval
from agent_eval.evaluation.scenario.metrics import ScenarioMetricsCalculator
from agent_eval.evaluation.scenario.models import (
    AggregationPolicy,
    MetricDefinition,
    ScenarioConfig,
    StageWeight,
)

__all__ = [
    "AggregationPolicy",
    "COURSEWARE_DEFAULT_METRICS",
    "COURSEWARE_DEFAULT_POLICY",
    "COURSEWARE_SCENARIO_CONFIG",
    "COURSEWARE_SCENARIO_ID",
    "MetricDefinition",
    "ScenarioConfig",
    "ScenarioMetricsCalculator",
    "ScenarioScoreAggregator",
    "StageWeight",
    "safe_eval",
]
