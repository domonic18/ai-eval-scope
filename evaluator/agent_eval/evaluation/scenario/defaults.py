"""courseware 默认聚合策略与指标定义。

等价复刻旧 ScoreAggregator / MetricsCalculator 在课件规则集上的行为：
- Reward = (S_format + S_common + w3·S_soft + w4·S_pref) / (1+1+w3+w4)，w3=w4=1
- DR = 格式通过率；CPR = 格式+常识双门控通过率；CondR = 双门控通过样本的 Reward 均值

权重取自 config.SCORE_AGGREGATION_WEIGHTS，阈值取自 config.METRIC_THRESHOLDS，
保证新旧实现数值完全一致（见 tests/unit/test_scenario_aggregation.py）。
未声明 aggregation_policy_id 的课件规则集自动套用本默认策略（对齐 04 §7'.2/§10.4）。
"""

from __future__ import annotations

from agent_eval.config import METRIC_THRESHOLDS, SCORE_AGGREGATION_WEIGHTS
from agent_eval.core.types import ConstraintTier
from agent_eval.evaluation.scenario.models import (
    AggregationPolicy,
    MetricDefinition,
    ScenarioConfig,
    StageWeight,
)

COURSEWARE_SCENARIO_ID = "courseware"


def _build_default_policy() -> AggregationPolicy:
    """构造 courseware 默认 AggregationPolicy（等价旧 ScoreAggregator）。"""
    w = SCORE_AGGREGATION_WEIGHTS
    quality_skip = [ConstraintTier.HARD_GATE, ConstraintTier.HARD_SCORE]
    return AggregationPolicy(
        id="courseware-default",
        scenario_id=COURSEWARE_SCENARIO_ID,
        stage_weights=[
            StageWeight(stage_id="format", weight=w.format_pass, is_gate=True),
            StageWeight(stage_id="commonsense", weight=w.commonsense_pass, is_gate=True),
            # quality 拆为 soft / pref 两项，各自加权；weight 即旧 w3 / w4
            StageWeight(
                stage_id="quality",
                weight=w.w3,
                is_gate=False,
                id="soft",
                skip_tiers_in_reward=quality_skip,
                evaluator_weights=dict(w.soft_weights),
            ),
            StageWeight(
                stage_id="quality",
                weight=w.w4,
                is_gate=False,
                id="pref",
                skip_tiers_in_reward=quality_skip,
                evaluator_weights=dict(w.pref_weights),
            ),
        ],
        normalize_to=(0.0, 1.0),
    )


def _build_default_metrics() -> list[MetricDefinition]:
    """构造 courseware 默认 MetricDefinition 列表（等价旧 MetricsCalculator 指标）。"""
    t = METRIC_THRESHOLDS
    return [
        MetricDefinition(
            id="courseware:document_rate",
            name="交付率 DR",
            expression="count(format_gate) / total",
            threshold=t.dr,
            unit="ratio",
        ),
        MetricDefinition(
            id="courseware:constraint_pass_rate",
            name="约束通过率 CPR",
            expression="count(both(format_gate, commonsense_gate)) / total",
            threshold=t.cpr,
            unit="ratio",
        ),
        MetricDefinition(
            id="courseware:reward",
            name="平均 Reward",
            expression="mean(reward)",
            threshold=t.avg_reward,
            unit="score",
        ),
        MetricDefinition(
            id="courseware:soft",
            name="平均内容质量",
            expression="mean(s_soft)",
            unit="score",
        ),
        MetricDefinition(
            id="courseware:pref",
            name="平均用户偏好",
            expression="mean(s_pref)",
            unit="score",
        ),
        MetricDefinition(
            id="courseware:conditional_reward",
            name="条件 Reward CondR",
            expression="gated_mean(reward, format_gate, commonsense_gate)",
            unit="score",
        ),
    ]


COURSEWARE_DEFAULT_POLICY: AggregationPolicy = _build_default_policy()
COURSEWARE_DEFAULT_METRICS: list[MetricDefinition] = _build_default_metrics()

COURSEWARE_SCENARIO_CONFIG: ScenarioConfig = ScenarioConfig(
    scenario_id=COURSEWARE_SCENARIO_ID,
    aggregation_policy=COURSEWARE_DEFAULT_POLICY,
    metric_definitions=COURSEWARE_DEFAULT_METRICS,
)
