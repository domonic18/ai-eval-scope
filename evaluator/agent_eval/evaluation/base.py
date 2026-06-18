"""评估器基类 — BaseEvaluator ABC。

所有评估器的统一接口，定义 evaluate() 返回 ConstraintResult。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from agent_eval.core.types import ConstraintTier, EvalMethod, EvalStatus
from agent_eval.evaluation.models import ConstraintResult


class BaseEvaluator(ABC):
    """评估器抽象基类。

    子类必须实现 evaluate() 方法，返回 ConstraintResult。
    可选重写 setup() 接收评估器参数。

    类属性：
        evaluator_id: 评估器唯一标识（如 "format.response_format"）
        name: 人类可读名称
        tier: 约束层级（HARD_GATE / HARD_SCORE / SOFT / PREFERENCE）
        method: 评估方法（RULE / FACT_VERIFY / MATH_VERIFY / LLM_JUDGE / ...）
    """

    evaluator_id: str = ""
    name: str = ""
    tier: ConstraintTier = ConstraintTier.SOFT
    method: EvalMethod = EvalMethod.RULE

    def __init__(self) -> None:
        self.params: dict[str, Any] = {}

    def setup(self, params: dict[str, Any]) -> None:
        """配置评估器参数（从 YAML 规则的 params 字段加载）。

        Args:
            params: 评估器参数字典。
        """
        self.params = params

    @abstractmethod
    def evaluate(self, sample: Any, context: dict[str, Any]) -> ConstraintResult:
        """执行评估，返回约束检查结果。

        Args:
            sample: 待评估的样本（通常为 ExecutionPackage 或文件路径）。
            context: 评估上下文（含约束条件、任务信息等）。

        Returns:
            ConstraintResult 实例。
        """
        ...

    def _make_result(
        self,
        *,
        status: EvalStatus,
        score: float,
        reason: str,
        raw_score: float | None = None,
        details: dict[str, Any] | None = None,
        duration_ms: float = 0.0,
        module_results: list[dict[str, Any]] | None = None,
    ) -> ConstraintResult:
        """便捷方法：构造 ConstraintResult。"""
        return ConstraintResult(
            constraint_id=self.evaluator_id,
            name=self.name,
            tier=self.tier,
            status=status,
            score=score,
            raw_score=raw_score,
            reason=reason,
            details=details or {},
            duration_ms=duration_ms,
            module_results=module_results,
        )
