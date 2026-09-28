"""稳定性控制器 — 多次采样取中位数 + 置信度判定。"""

from __future__ import annotations

import statistics
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

from agent_eval.config import STABILITY_DEFAULTS
from agent_eval.llm.judge.template_manager import JudgeDimension


@dataclass
class StableResult:
    """稳定性评估结果。"""

    scores: dict[str, float]  # dim_id -> 中位数得分
    confidence: dict[str, str]  # dim_id -> "high" | "low"
    all_samples: list[dict[str, Any]] = field(default_factory=list)
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
        max_concurrency: int = STABILITY_DEFAULTS.max_concurrency,
    ) -> None:
        """初始化稳定性控制器。

        Args:
            num_samples: 采样次数。
            stddev_threshold: 标准差阈值，超过则标记为低置信度。
            max_concurrency: 采样并发上限（实际并发 = min(max_concurrency, 采样数)，
                =1 串行）。
        """
        self.num_samples = num_samples
        self.stddev_threshold = stddev_threshold
        self.max_concurrency = max(1, max_concurrency)

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
        if n < 1:
            # 尾部防线：0/负数会使 range(n) 为空，炸出难懂的「no median for empty
            # data」——在此给出语义化报错（包级防呆在落盘校验 rule_refs，双端同拦）
            raise ValueError(
                f"num_samples 必须 ≥ 1（收到 {n}）——该参数决定判官独立采样次数"
                "（prompts 模板的 num_samples 字段）"
            )
        samples: list[dict[str, Any] | None] = [None] * n
        workers = min(self.max_concurrency, n)
        if workers <= 1:
            for i in range(n):
                samples[i] = judge_fn(i)
        else:
            # 有界并发采样：seed 已按 sample_index 区分、采样间零数据依赖，并发只改
            # 墙钟不改语义。按下标回填保证 all_samples 顺序与串行一致（调用方的
            # 「末样本」语义依赖它）；首个异常按下标顺序原样上抛（与串行短路等价），
            # 在飞采样不等待——异常路径不为补齐结果拖住整次 judge。
            executor = ThreadPoolExecutor(max_workers=workers)
            try:
                futures = [executor.submit(judge_fn, i) for i in range(n)]
                for i, future in enumerate(futures):
                    samples[i] = future.result()
            finally:
                executor.shutdown(wait=False, cancel_futures=True)
        all_samples: list[dict[str, Any]] = [s for s in samples if s is not None]

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
