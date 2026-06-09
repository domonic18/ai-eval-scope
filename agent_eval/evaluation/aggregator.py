"""ScoreAggregator — 评分聚合。

实现 Reward 公式：Reward = S_format + S_common + w3 × S_soft + w4 × S_pref
"""

from __future__ import annotations

from agent_eval.core.types import EvalStatus
from agent_eval.evaluation.models import SampleResult, SampleScore


class ScoreAggregator:
    """评分聚合器 — 将约束结果聚合为 Reward Score。

    Args:
        w3: 软约束乘数，默认 1.0。
        w4: 偏好约束乘数，默认 1.0。
        soft_weights: 软约束各评估器的权重映射。
        pref_weights: 偏好约束各评估器的权重映射。
    """

    def __init__(
        self,
        w3: float = 1.0,
        w4: float = 1.0,
        soft_weights: dict[str, float] | None = None,
        pref_weights: dict[str, float] | None = None,
    ) -> None:
        self.w3 = w3
        self.w4 = w4
        self.soft_weights = soft_weights or {
            "soft.content_density": 0.25,
            "soft.visual_consistency": 0.25,
            "soft.teaching_logic": 0.25,
            "soft.content_diversity": 0.25,
        }
        self.pref_weights = pref_weights or {
            "pref.style_preference": 0.33,
            "pref.depth_preference": 0.33,
            "pref.request_fulfillment": 0.34,
        }

    def aggregate(self, result: SampleResult) -> SampleScore:
        """将 SampleResult 聚合为 SampleScore。

        Args:
            result: 单个样本的完整评估结果。

        Returns:
            SampleScore 实例（含各维度得分和 Reward）。
        """
        s_format = self._format(result)
        s_common = self._commonsense(result)
        s_soft = self._weighted(result, "quality", self.soft_weights)
        s_pref = self._weighted(result, "quality", self.pref_weights)

        reward = s_format + s_common + self.w3 * s_soft + self.w4 * s_pref

        return SampleScore(
            sample_id=result.sample_id,
            s_format=s_format,
            s_common=s_common,
            s_soft=s_soft,
            s_pref=s_pref,
            reward=reward,
        )

    def _format(self, r: SampleResult) -> float:
        """计算格式约束得分。

        全通过 → +1，任一失败 → -3。
        """
        s = r.stage_results.get("format")
        if not s or s.status == EvalStatus.SKIP:
            return 0.0
        return 1.0 if s.status == EvalStatus.PASS else -3.0

    def _commonsense(self, r: SampleResult) -> float:
        """计算常识约束得分。

        全通过 → +1，任一失败 → 0。
        """
        s = r.stage_results.get("commonsense")
        if not s or s.status in (EvalStatus.SKIP, EvalStatus.FAIL):
            return 0.0
        return 1.0

    def _weighted(
        self,
        r: SampleResult,
        stage_id: str,
        weights: dict[str, float],
    ) -> float:
        """计算加权得分（用于软约束和偏好约束）。

        归一化到 [0, 1]。
        """
        s = r.stage_results.get(stage_id)
        if not s or s.status == EvalStatus.SKIP:
            return 0.0

        wsum = 0.0
        for cr in s.constraint_results:
            if cr.constraint_id in weights:
                wsum += weights[cr.constraint_id] * cr.score

        wtotal = sum(weights.values())
        return wsum / wtotal if wtotal > 0 else 0.0
