"""稳定性控制器 — 多次采样取中位数 + 置信度判定。"""

from __future__ import annotations

import statistics
from collections.abc import Callable
from dataclasses import dataclass, field

from agent_eval.config import STABILITY_DEFAULTS
from agent_eval.llm.judge.template_manager import JudgeDimension


@dataclass
class StableResult:
    """稳定性评估结果。"""

    scores: dict[str, float]  # dim_id -> 中位数得分
    confidence: dict[str, str]  # dim_id -> "high" | "low"
    all_samples: list[dict[str, float]] = field(default_factory=list)
    num_samples: int = 0


class StabilityController:
    """控制 LLM 评估结果的稳定性。

    方法：
    1. 多次独立采样：调用 judge_fn 多次，每次传入不同 seed
    2. 取中位数：每个维度取所有采样的中位数作为最终得分
    3. 置信度判定：标准差 > 阈值 → 标记 "low"
    """

    def __init__(
        self,
        num_samples: int = STABILITY_DEFAULTS.num_samples,
        stddev_threshold: float = STABILITY_DEFAULTS.stddev_threshold,
    ) -> None:
        """初始化稳定性控制器。

        Args:
            num_samples: 采样次数。
            stddev_threshold: 标准差阈值，超过则标记为低置信度。
        """
        self.num_samples = num_samples
        self.stddev_threshold = stddev_threshold

    def evaluate_stable(
        self,
        judge_fn: Callable[[int], dict[str, float]],
        dimensions: list[JudgeDimension],
        *,
        num_samples: int | None = None,
    ) -> StableResult:
        """执行多次采样，计算中位数和置信度。

        Args:
            judge_fn: 接收 seed 参数，返回 {dim_id: score} 的函数。
            dimensions: 评分维度列表。
            num_samples: 本次采样次数，None 时使用构造默认值。
                允许按模板覆盖（如视觉模板 num_samples=1 节省成本）。

        Returns:
            StableResult 包含最终得分和置信度。
        """
        n = self.num_samples if num_samples is None else num_samples
        all_samples: list[dict[str, float]] = []
        for i in range(n):
            scores = judge_fn(i)
            all_samples.append(scores)

        final_scores: dict[str, float] = {}
        confidence: dict[str, str] = {}

        for dim in dimensions:
            dim_scores = [s.get(dim.dim_id, 0.0) for s in all_samples]

            if len(dim_scores) == 1:
                final_scores[dim.dim_id] = dim_scores[0]
                confidence[dim.dim_id] = "high"
            else:
                median = statistics.median(dim_scores)
                final_scores[dim.dim_id] = median

                # 标准差计算（需要至少 2 个样本）
                stddev = statistics.stdev(dim_scores) if len(dim_scores) >= 2 else 0.0
                confidence[dim.dim_id] = "high" if stddev <= self.stddev_threshold else "low"

        return StableResult(
            scores=final_scores,
            confidence=confidence,
            all_samples=all_samples,
            num_samples=len(all_samples),
        )
