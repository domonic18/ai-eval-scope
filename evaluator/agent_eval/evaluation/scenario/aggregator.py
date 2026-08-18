"""ScenarioScoreAggregator — 按 AggregationPolicy 数据驱动地聚合 Reward。

对齐 04 评估引擎设计 §7'.3。与旧 ScoreAggregator 的关键差异（均为保证 courseware
等价复刻）：
1. 阶段由 policy.stage_weights 声明，不再写死 format/commonsense/quality；
2. 分母仅计入实际参与计算的阶段（stage 缺失/SKIP 时不计入），而非旧公式固定分母；
3. evaluator_weights 挂在 StageWeight 上，允许 quality 拆为 soft/pref 两项。
"""

from __future__ import annotations

from agent_eval.core.types import EvalStatus
from agent_eval.evaluation.models import SampleResult, StageResult
from agent_eval.evaluation.scenario.models import StageWeight


class ScenarioScoreAggregator:
    """按 AggregationPolicy 把 SampleResult 聚合为样本级 metrics（含 reward）。

    构造时传入 AggregationPolicy；aggregate 返回 ``dict[str, float]``，
    至少含 ``reward``，并为声明了 ``id`` 的 StageWeight 暴露其阶段得分。
    """

    def __init__(self, policy):  # noqa: ANN001 (避免循环：用前向字符串类型)
        self.policy = policy

    def aggregate(self, result: SampleResult) -> dict[str, float]:
        """聚合单样本，返回 ``Record[metric_id, number]``，至少含 ``reward``。"""
        lo, hi = self.policy.normalize_to
        numer = 0.0
        denom = 0.0
        per_stage: dict[str, float] = {}
        for sw in self.policy.stage_weights:
            stage = result.stage_results.get(sw.stage_id)
            s = self._stage_score(stage, sw)
            if s is None:
                # 阶段未参与计算（如仅选门控时质量阶段被跳过），不计入分母
                continue
            numer += sw.weight * s
            denom += sw.weight
            if sw.id:
                per_stage[sw.id] = s
        span = hi - lo
        reward = lo + span * (numer / denom) if denom > 0 else lo
        return {"reward": reward, **per_stage}

    def _stage_score(self, stage: StageResult | None, sw: StageWeight) -> float | None:
        """计算单个阶段的归一化得分（归一化区间映射前，∈ [0,1]）。

        返回 None 表示该阶段未参与计算（stage 不存在且为门控阶段，或 stage.status == SKIP）。
        """
        if not sw.evaluator_weights:
            # 门控语义：无 evaluator_weights → 纯门控阶段
            #   - stage 存在且 gate_passed=True → 1.0
            #   - stage 不存在（未参与计算，如仅选门控时质量阶段被跳过）→ None（不参与）
            #   - stage 存在但 gate_passed=False → 0.0（门控失败，按失败计）
            if stage is None:
                return None  # 未参与计算
            return 1.0 if stage.gate_passed else 0.0
        # 加权语义：缺失/SKIP → None（不参与）；否则按 evaluator_weights 加权平均
        if stage is None or stage.status == EvalStatus.SKIP:
            return None
        ew = sw.evaluator_weights
        skip_tiers = set(sw.skip_tiers_in_reward)
        wsum = 0.0
        for cr in stage.constraint_results:
            if cr.status == EvalStatus.SKIP:
                continue
            if cr.tier in skip_tiers:
                continue
            if cr.constraint_id in ew:
                wsum += ew[cr.constraint_id] * cr.score
        wtotal = sum(ew.values())
        return wsum / wtotal if wtotal > 0 else 0.0
