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

# 自动暴露为表达式的 SampleResult 数值标量字段（场景无关的过程元数据）。
# 场景化质量分（soft/pref 等）不在此列 —— 它们经 stage_metrics dict 动态暴露（见 _build_context）。
_SCALAR_FIELDS = (
    "reward",
    "total_duration_ms",
    "llm_calls",
    "token_usage",
)


class ScenarioMetricsCalculator:
    """声明式批量指标计算器。

    从一组 SampleResult 计算每个 MetricDefinition.id 对应的运行级指标值。
    """

    def __init__(
        self,
        definitions: list[MetricDefinition],
        *,
        stage_ids: list[str] | None = None,
    ) -> None:
        self.definitions = definitions
        # policy 声明的 stage_id：确保 expression 引用的 <stage>_gate 即使该 stage
        # 在本次结果中缺失（如仅评估 format）也能取到默认全 False 数组，而非未知变量。
        self.stage_ids = stage_ids

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

        # 1. 样本数值标量字段（过程元数据）→ 同长数组
        for fld in _SCALAR_FIELDS:
            ctx[fld] = [getattr(r, fld, 0.0) for r in results]

        # 2. 场景化样本指标（stage_metrics）每个 key → 同名数组变量
        #    key = StageWeight.id（soft/pref）+ reward；expression 直接引用（如 mean(soft)）
        #    同时预填 metric definitions 表达式中引用的变量，即使该 stage 未参与也填入空数组（mean([])=0）。
        metric_keys: set[str] = set()
        for r in results:
            metric_keys.update(r.stage_metrics.keys())
        # 从 expressions 提取变量名：支持 mean(soft)、gated_mean(reward, format_gate) 等形式
        import re
        for d in self.definitions:
            for match in re.finditer(r'(?:mean|gated_mean|count|sum|min|max|abs|round)\s*\(([^)]+)\)', d.expression):
                for v in match.group(1).split(','):
                    v = v.strip().split('.')[0]
                    if v and v not in ('total', 'len'):
                        metric_keys.add(v)
        for key in metric_keys:
            ctx[key] = [r.stage_metrics.get(key, 0.0) for r in results]

        # 3. stage gate/score 数组：policy 声明的 stage ∪ results 出现的 stage（缺失填默认）
        stage_ids: set[str] = set(self.stage_ids or [])
        for r in results:
            stage_ids.update(r.stage_results.keys())
        for sid in sorted(stage_ids):
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
