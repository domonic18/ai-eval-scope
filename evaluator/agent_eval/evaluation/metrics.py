"""MetricsCalculator — 批量指标计算。

计算 DR / CPR / Reward / Time 等指标。
"""

from __future__ import annotations

from agent_eval.core.types import EvalStatus
from agent_eval.evaluation.models import MetricsReport, SampleResult, StageResult


class MetricsCalculator:
    """批量指标计算器。

    从一组 SampleResult 计算汇总指标。
    """

    def compute(
        self,
        results: list[SampleResult],
        *,
        run_id: str = "",
    ) -> MetricsReport:
        """计算批量评估指标（deprecated：保留作 courseware 等价对照基准）。

        输出场景化 metrics dict（courseware:* 键），与新 ScenarioMetricsCalculator 对齐；
        soft/pref/reward 从 SampleResult.stage_metrics 读取（由聚合器填充）。
        """
        total = len(results)
        if total == 0:
            return MetricsReport(run_id=run_id)

        # DR: 格式通过数 / 总数
        fmt_pass = sum(
            1
            for r in results
            if r.stage_results.get(
                "format", StageResult(stage_id="format", status=EvalStatus.FAIL)
            ).gate_passed
        )

        # CPR: 格式 + 常识均通过数 / 总数
        com_pass = sum(
            1
            for r in results
            if r.stage_results.get(
                "format", StageResult(stage_id="format", status=EvalStatus.FAIL)
            ).gate_passed
            and r.stage_results.get(
                "commonsense", StageResult(stage_id="commonsense", status=EvalStatus.FAIL)
            ).gate_passed
        )

        # 内容质量 / 用户偏好 / reward 从 stage_metrics 读（ScenarioScoreAggregator 输出）
        avg_soft = sum(r.stage_metrics.get("soft", 0.0) for r in results) / total
        avg_pref = sum(r.stage_metrics.get("pref", 0.0) for r in results) / total
        avg_reward = sum(r.reward for r in results) / total

        failure_breakdown = self._breakdown(results)
        llm_skipped = self._llm_skipped(results)

        return MetricsReport(
            run_id=run_id,
            total_samples=total,
            metrics={
                "courseware:document_rate": fmt_pass / total,
                "courseware:constraint_pass_rate": com_pass / total,
                "courseware:reward": avg_reward,
                "courseware:soft": avg_soft,
                "courseware:pref": avg_pref,
            },
            avg_time_ms=sum(r.total_duration_ms for r in results) / total,
            sample_scores=[{"sample_id": r.sample_id, **r.stage_metrics} for r in results],
            failure_breakdown=failure_breakdown,
            llm_skipped=llm_skipped,
        )

    def _breakdown(self, results: list[SampleResult]) -> dict[str, int]:
        """统计各约束 ID 的失败次数。"""
        breakdown: dict[str, int] = {}
        for r in results:
            for sr in r.stage_results.values():
                for cr in sr.constraint_results:
                    if cr.status == EvalStatus.FAIL:
                        breakdown[cr.constraint_id] = breakdown.get(cr.constraint_id, 0) + 1
        return breakdown

    def _llm_skipped(self, results: list[SampleResult]) -> int:
        """统计因 LLM 不可用而 SKIP 的约束数（reason 含 'LLM'）。"""
        count = 0
        for r in results:
            for sr in r.stage_results.values():
                for cr in sr.constraint_results:
                    if cr.status == EvalStatus.SKIP and "LLM" in (cr.reason or ""):
                        count += 1
        return count
