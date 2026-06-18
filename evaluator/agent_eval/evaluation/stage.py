"""PipelineStage — 单阶段执行器。

管理该阶段内所有 Evaluator 的执行与门控判定。
"""

from __future__ import annotations

import time
from typing import Any

from agent_eval.core.types import ConstraintTier, EvalStatus
from agent_eval.evaluation.base import BaseEvaluator
from agent_eval.evaluation.models import ConstraintResult, StageResult


class PipelineStage:
    """单阶段执行器，管理该阶段内所有 Evaluator 的执行与门控判定。

    Args:
        stage_id: 阶段标识（如 "format", "commonsense", "quality"）。
        evaluators: 该阶段的评估器列表。
        short_circuit_policy: 短路策略 — "fail_fast" 或 "continue_all"。
    """

    def __init__(
        self,
        stage_id: str,
        evaluators: list[BaseEvaluator],
        short_circuit_policy: str = "fail_fast",
    ) -> None:
        self.stage_id = stage_id
        self.evaluators = evaluators
        self.short_circuit_policy = short_circuit_policy

    def execute(self, sample: Any, context: dict[str, Any]) -> StageResult:
        """执行该阶段所有评估器。

        Args:
            sample: 待评估的样本。
            context: 评估上下文。

        Returns:
            StageResult 实例。
        """
        stage_result = StageResult(
            stage_id=self.stage_id,
            status=EvalStatus.PASS,
        )
        stage_start = time.monotonic()
        gate_passed = True

        for evaluator in self.evaluators:
            ev_start = time.monotonic()
            try:
                constraint_result = evaluator.evaluate(sample, context)
            except Exception as e:
                constraint_result = ConstraintResult(
                    constraint_id=evaluator.evaluator_id,
                    name=evaluator.name,
                    tier=evaluator.tier,
                    status=EvalStatus.ERROR,
                    score=0.0,
                    reason=f"评估器执行异常: {e}",
                    duration_ms=(time.monotonic() - ev_start) * 1000,
                )
                gate_passed = False

            # 补充耗时（如评估器未自行计算）
            if constraint_result.duration_ms == 0.0:
                constraint_result.duration_ms = (time.monotonic() - ev_start) * 1000

            stage_result.constraint_results.append(constraint_result)

            # 门控判定：
            # - HARD_GATE 失败 → 门控未通过（格式不对无法继续）
            # - HARD_SCORE 失败 → 门控未通过但不中断阶段内后续评估器
            #   （内容有错不代表后续 soft/pref 评估无意义）
            if evaluator.tier == ConstraintTier.HARD_GATE:
                if constraint_result.status == EvalStatus.FAIL:
                    gate_passed = False
                    # fail_fast 模式下立即终止本阶段
                    if self.short_circuit_policy == "fail_fast":
                        break
            elif evaluator.tier == ConstraintTier.HARD_SCORE:
                if constraint_result.status == EvalStatus.FAIL:
                    gate_passed = False
                    # HARD_SCORE 失败不中断阶段内其他评估器，继续执行

        stage_result.gate_passed = gate_passed
        stage_result.status = EvalStatus.PASS if gate_passed else EvalStatus.FAIL
        stage_result.duration_ms = (time.monotonic() - stage_start) * 1000

        return stage_result
