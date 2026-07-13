"""ScenarioMetricsCalculator — 按 MetricDefinition 声明式计算运行级指标。

对齐 04 评估引擎设计 §7'.4。指标表达式经安全引擎（expr.safe_eval）求值，
上下文变量见 ``expr`` 模块文档。courseware 默认指标集与旧 MetricsCalculator 的
DR/CPR/Reward/Soft/Pref/CondR 逐一等价。
"""

from __future__ import annotations

from typing import Any

from agent_eval.core.types import EvalStatus
from agent_eval.evaluation.models import SampleResult
from agent_eval.evaluation.scenario.expr import safe_eval
from agent_eval.evaluation.scenario.models import MetricDefinition

# 自动暴露为表达式的 SampleResult 数值标量字段
_SCALAR_FIELDS = (
    "reward",
    "s_format",
    "s_common",
    "s_soft",
    "s_pref",
    "total_duration_ms",
    "llm_calls",
    "token_usage",
)


class ScenarioMetricsCalculator:
    """声明式批量指标计算器。

    从一组 SampleResult 计算每个 MetricDefinition.id 对应的运行级指标值。
    """

    def __init__(self, definitions: list[MetricDefinition]) -> None:
        self.definitions = definitions

    def compute(self, results: list[SampleResult]) -> dict[str, float]:
        """计算所有指标，返回 ``Record[metric_id, number]``。"""
        if not self.definitions or not results:
            return {}
        ctx = self._build_context(results)
        return {d.id: safe_eval(d.expression, ctx) for d in self.definitions}

    def _build_context(self, results: list[SampleResult]) -> dict[str, Any]:
        total = len(results)
        ctx: dict[str, Any] = {"total": total}
        if total == 0:
            return ctx

        # 1. 样本数值标量字段 → 同长数组
        for field in _SCALAR_FIELDS:
            ctx[field] = [getattr(r, field, 0.0) for r in results]

        # 2. 每个出现的 stage → <stage_id>_gate 布尔数组（及 <stage_id>_score）
        stage_ids: set[str] = set()
        for r in results:
            stage_ids.update(r.stage_results.keys())
        for sid in stage_ids:
            gate_arr: list[bool] = []
            score_arr: list[float] = []
            for r in results:
                sr = r.stage_results.get(sid)
                if sr is None:
                    gate_arr.append(False)
                    score_arr.append(0.0)
                else:
                    gate_arr.append(bool(sr.gate_passed))
                    score_arr.append(sr.category_score if sr.status != EvalStatus.SKIP else 0.0)
            ctx[f"{sid}_gate"] = gate_arr
            ctx[f"{sid}_score"] = score_arr
        return ctx
