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
    """构造 courseware 默认 MetricDefinition 列表（等价旧 MetricsCalculator 指标）。

    每项含 explain（前端 ? hover 说明，对齐旧 METRIC_EXPLAIN），由运行快照携带。
    """
    t = METRIC_THRESHOLDS
    return [
        MetricDefinition(
            id="courseware:document_rate",
            name="交付率 DR",
            expression="count(format_gate) / total",
            threshold=t.dr,
            unit="ratio",
            explain={
                "title": "DR · Delivery Rate 交付率",
                "rows": [
                    {
                        "dt": "定义",
                        "dd": "能正常打开、格式符合基本要求的样本占多少——连格式都不对就没法使用。",
                        "tone": "primary",
                    },
                    {"dt": "计算", "dd": "格式合格的样本数 ÷ 全部样本数"},
                    {
                        "dt": "标准",
                        "dd": f"达标线 ≥ {t.dr}（即 {round(t.dr * 100)}%）；低于则这批整体不合格。",
                        "tone": "danger",
                    },
                ],
            },
        ),
        MetricDefinition(
            id="courseware:constraint_pass_rate",
            name="约束通过率 CPR",
            expression="count(both(format_gate, commonsense_gate)) / total",
            threshold=t.cpr,
            unit="ratio",
            explain={
                "title": "CPR · Constraint Pass Rate 约束通过率",
                "rows": [
                    {
                        "dt": "定义",
                        "dd": "格式 + 常识双门控都通过的样本占比——内容基本正确、无明显硬伤。",
                        "tone": "primary",
                    },
                    {"dt": "计算", "dd": "双门控通过样本数 ÷ 全部样本数"},
                    {
                        "dt": "标准",
                        "dd": f"达标线 ≥ {t.cpr}；低于则存在较多常识性错误。",
                        "tone": "danger",
                    },
                ],
            },
        ),
        MetricDefinition(
            id="courseware:reward",
            name="平均 Reward",
            expression="mean(reward)",
            threshold=t.avg_reward,
            unit="score",
            explain={
                "title": "Reward · 综合评分",
                "rows": [
                    {
                        "dt": "定义",
                        "dd": "归一化到 [0,1] 的综合质量分，融合门控与软/偏好质量。",
                        "tone": "primary",
                    },
                    {"dt": "计算", "dd": "(S_format + S_common + S_soft + S_pref) / 4"},
                    {
                        "dt": "标准",
                        "dd": f"达标线 ≥ {t.avg_reward}；综合质量合格。",
                        "tone": "success",
                    },
                ],
            },
        ),
        MetricDefinition(
            id="courseware:soft",
            name="平均内容质量",
            expression="mean(s_soft)",
            unit="score",
            explain={
                "title": "Soft · 内容质量分",
                "rows": [
                    {
                        "dt": "定义",
                        "dd": "教学逻辑、内容多样性等软约束维度的平均得分（独立指标，不混入 Reward）。",
                        "tone": "primary",
                    },
                    {"dt": "范围", "dd": "[0, 1]，越高越好"},
                ],
            },
        ),
        MetricDefinition(
            id="courseware:pref",
            name="平均用户偏好",
            expression="mean(s_pref)",
            unit="score",
            explain={
                "title": "Pref · 用户偏好分",
                "rows": [
                    {
                        "dt": "定义",
                        "dd": "风格、深度、需求满足度等偏好维度的平均得分（独立指标）。",
                        "tone": "primary",
                    },
                    {"dt": "范围", "dd": "[0, 1]，越高越好"},
                ],
            },
        ),
        MetricDefinition(
            id="courseware:conditional_reward",
            name="条件 Reward CondR",
            expression="gated_mean(reward, format_gate, commonsense_gate)",
            unit="score",
            explain={
                "title": "CondR · Conditional Reward",
                "rows": [
                    {
                        "dt": "定义",
                        "dd": "仅统计通过双门控样本的 Reward 均值——排除格式/常识失败后的真实质量。",
                        "tone": "primary",
                    },
                    {"dt": "范围", "dd": "[0, 1]"},
                ],
            },
        ),
    ]


COURSEWARE_DEFAULT_POLICY: AggregationPolicy = _build_default_policy()
COURSEWARE_DEFAULT_METRICS: list[MetricDefinition] = _build_default_metrics()

COURSEWARE_SCENARIO_CONFIG: ScenarioConfig = ScenarioConfig(
    scenario_id=COURSEWARE_SCENARIO_ID,
    aggregation_policy=COURSEWARE_DEFAULT_POLICY,
    metric_definitions=COURSEWARE_DEFAULT_METRICS,
)
