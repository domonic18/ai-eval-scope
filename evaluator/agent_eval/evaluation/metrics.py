"""MetricsCalculator — 批量指标计算。

计算 DR / CPR / Reward / CondR / Time 等指标。
"""

from __future__ import annotations

from agent_eval.core.types import EvalStatus
from agent_eval.evaluation.models import MetricsReport, SampleResult, SampleScore, StageResult


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
        """计算批量评估指标。

        Args:
            results: 所有样本的评估结果列表。
            run_id: 运行 ID。

        Returns:
            MetricsReport 实例。
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

        # 通过双门控的样本（用于 CondR）
        gated = [r for r in results if self._passed_gates(r)]

        # Reward 分布
        rewards = [r.reward for r in results]

        # 失败分类
        failure_breakdown = self._breakdown(results)

        # LLM 不可用导致的跳过数
        llm_skipped = self._llm_skipped(results)

        return MetricsReport(
            run_id=run_id,
            total_samples=total,
            dr=fmt_pass / total,
            cpr=com_pass / total,
            avg_reward=sum(rewards) / total,
            cond_r=(sum(r.reward for r in gated) / len(gated)) if gated else 0.0,
            avg_time_ms=sum(r.total_duration_ms for r in results) / total,
            sample_scores=[
                SampleScore(
                    sample_id=r.sample_id,
                    s_format=r.s_format,
                    s_common=r.s_common,
                    s_soft=r.s_soft,
                    s_pref=r.s_pref,
                    reward=r.reward,
                )
                for r in results
            ],
            failure_breakdown=failure_breakdown,
            llm_skipped=llm_skipped,
        )

    def _passed_gates(self, r: SampleResult) -> bool:
        """判断样本是否通过了格式 + 常识双门控。"""
        f = r.stage_results.get("format")
        c = r.stage_results.get("commonsense")
        return bool(f and f.gate_passed and c and c.gate_passed)

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
