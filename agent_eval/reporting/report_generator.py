"""ReportGenerator — Markdown + JSON 双格式报告生成。

生成任务级和聚合级两种报告：
- 任务级: 每个评估样本的约束结果、得分、LLM 溯源
- 聚合级: DR/CPR/Reward 指标表、阈值对比、失败项明细
"""

from __future__ import annotations

from typing import Any

from agent_eval.core.types import EvalStatus
from agent_eval.evaluation.models import (
    ConstraintResult,
    MetricsReport,
    SampleResult,
)

# 默认阈值
_DEFAULT_THRESHOLDS: dict[str, float] = {
    "DR": 0.95,
    "CPR": 0.90,
    "avg_reward": 0.70,
}

# 指标中文名映射
_METRIC_LABELS: dict[str, str] = {
    "DR": "交付率 (DR)",
    "CPR": "约束通过率 (CPR)",
    "avg_reward": "平均 Reward",
    "condR": "条件 Reward (CondR)",
    "avg_time_ms": "平均耗时 (ms)",
}

# 阶段中文名映射
_STAGE_LABELS: dict[str, str] = {
    "format": "格式门控",
    "commonsense": "常识检查",
    "quality": "质量评估",
}

# 约束层中文标记
_TIER_MARKERS: dict[str, str] = {
    "HARD_GATE": "🔴 硬门控",
    "HARD_SCORE": "🟠 硬评分",
    "SOFT": "🟡 软约束",
    "PREFERENCE": "🔵 偏好",
}


class ReportGenerator:
    """报告生成器 — 将评估结果转换为 Markdown + JSON 格式。

    Args:
        thresholds: 指标阈值映射，默认 DR ≥ 0.95, CPR ≥ 0.90, avg_reward ≥ 0.70。
    """

    def __init__(self, thresholds: dict[str, float] | None = None) -> None:
        self.thresholds = thresholds or dict(_DEFAULT_THRESHOLDS)

    # ─── 任务级报告 ───

    def generate_task_report(
        self,
        sample_result: SampleResult,
    ) -> tuple[str, dict[str, Any]]:
        """生成单任务报告。

        Returns:
            (markdown_content, json_dict)
        """
        md = self._render_task_markdown(sample_result)
        json_dict = sample_result.to_dict()
        return md, json_dict

    def _render_task_markdown(self, sample_result: SampleResult) -> str:
        """渲染任务级 Markdown。"""
        lines: list[str] = []
        lines.append(f"# 评估报告: {sample_result.sample_id}")
        lines.append("")

        # 状态
        status_icon = "✅" if sample_result.status == EvalStatus.PASS else "❌"
        lines.append(f"**状态**: {status_icon} {sample_result.status.value}")
        lines.append(f"**Reward**: {sample_result.reward:.2f}")
        lines.append(f"**耗时**: {sample_result.total_duration_ms:.0f}ms")
        lines.append("")

        # 各阶段得分
        lines.append("## 得分概览")
        lines.append("")
        lines.append("| 维度 | 得分 |")
        lines.append("|------|------|")
        lines.append(f"| S_format | {sample_result.s_format:+.1f} |")
        lines.append(f"| S_common | {sample_result.s_common:+.1f} |")
        lines.append(f"| S_soft | {sample_result.s_soft:.3f} |")
        lines.append(f"| S_pref | {sample_result.s_pref:.3f} |")
        lines.append(f"| **Reward** | **{sample_result.reward:.2f}** |")
        lines.append("")

        # 约束结果详情
        for stage_id, stage_result in sample_result.stage_results.items():
            stage_label = _STAGE_LABELS.get(stage_id, stage_id)
            gate_icon = "✅" if stage_result.gate_passed else "❌"
            lines.append(f"## {stage_label} {gate_icon}")
            lines.append("")

            if stage_result.status == EvalStatus.SKIP:
                lines.append("*阶段已跳过（前置门控未通过）*")
                lines.append("")
                continue

            if not stage_result.constraint_results:
                lines.append("*无约束检查结果*")
                lines.append("")
                continue

            lines.append("| 约束 | 层级 | 状态 | 得分 | 说明 |")
            lines.append("|------|------|------|------|------|")

            for cr in stage_result.constraint_results:
                status_icon = "✅" if cr.status == EvalStatus.PASS else "❌"
                tier_mark = _TIER_MARKERS.get(cr.tier.value, cr.tier.value)
                reason = cr.reason[:60] + "..." if len(cr.reason) > 60 else cr.reason
                lines.append(
                    f"| {cr.name} | {tier_mark} | {status_icon} | {cr.score:.2f} | {reason} |"
                )

            lines.append("")

            # LLM Judge 溯源信息
            llm_results = [
                cr for cr in stage_result.constraint_results if cr.judge_provider is not None
            ]
            if llm_results:
                lines.append("### LLM Judge 溯源")
                lines.append("")
                for cr in llm_results:
                    lines.append(f"- **{cr.name}**")
                    lines.append(f"  - Provider: `{cr.judge_provider}`")
                    lines.append(f"  - Model: `{cr.judge_model}`")
                    if cr.judge_record_path:
                        lines.append(f"  - 记录: `{cr.judge_record_path}`")
                lines.append("")

        return "\n".join(lines)

    # ─── 聚合报告 ───

    def generate_summary_report(
        self,
        metrics_report: MetricsReport,
    ) -> tuple[str, dict[str, Any]]:
        """生成聚合报告。

        Returns:
            (markdown_content, json_dict)
        """
        md = self._render_summary_markdown(metrics_report)
        json_dict = metrics_report.to_dict()
        return md, json_dict

    def _render_summary_markdown(self, metrics_report: MetricsReport) -> str:
        """渲染聚合 Markdown。"""
        lines: list[str] = []
        lines.append("# 评估聚合报告")
        lines.append("")
        lines.append(f"**运行 ID**: `{metrics_report.run_id}`")
        lines.append(f"**样本总数**: {metrics_report.total_samples}")
        lines.append("")

        # 指标概览
        lines.append("## 指标概览")
        lines.append("")
        lines.append("| 指标 | 值 | 目标 | 状态 |")
        lines.append("|------|-----|------|------|")

        metrics_data = {
            "DR": metrics_report.dr,
            "CPR": metrics_report.cpr,
            "avg_reward": metrics_report.avg_reward,
        }
        for metric_key, value in metrics_data.items():
            target = self.thresholds.get(metric_key)
            label = _METRIC_LABELS.get(metric_key, metric_key)
            if target is not None:
                status = "✅ PASS" if value >= target else "❌ BELOW"
                lines.append(f"| {label} | {value:.3f} | ≥{target:.2f} | {status} |")
            else:
                lines.append(f"| {label} | {value:.3f} | — | — |")

        # CondR
        cond_r = metrics_report.cond_r
        lines.append(f"| {_METRIC_LABELS.get('condR', 'CondR')} | {cond_r:.3f} | — | — |")
        lines.append(
            f"| {_METRIC_LABELS.get('avg_time_ms', '耗时')} | {metrics_report.avg_time_ms:.0f}ms | — | — |"
        )
        lines.append("")

        # 失败项明细
        if metrics_report.failure_breakdown:
            lines.append("## 失败项明细")
            lines.append("")
            lines.append("| 约束 ID | 失败次数 |")
            lines.append("|---------|----------|")
            for cid, count in sorted(
                metrics_report.failure_breakdown.items(),
                key=lambda x: x[1],
                reverse=True,
            ):
                lines.append(f"| `{cid}` | {count} |")
            lines.append("")

        # 样本得分一览
        if metrics_report.sample_scores:
            lines.append("## 样本得分一览")
            lines.append("")
            lines.append("| 样本 | S_format | S_common | S_soft | S_pref | Reward |")
            lines.append("|------|----------|----------|--------|--------|--------|")
            for s in metrics_report.sample_scores:
                if isinstance(s, dict):
                    lines.append(
                        f"| {s.get('sample_id', '?')} "
                        f"| {s.get('s_format', 0):+.1f} "
                        f"| {s.get('s_common', 0):+.1f} "
                        f"| {s.get('s_soft', 0):.3f} "
                        f"| {s.get('s_pref', 0):.3f} "
                        f"| **{s.get('reward', 0):.2f}** |"
                    )
                else:
                    lines.append(
                        f"| {s.sample_id} "
                        f"| {s.s_format:+.1f} "
                        f"| {s.s_common:+.1f} "
                        f"| {s.s_soft:.3f} "
                        f"| {s.s_pref:.3f} "
                        f"| **{s.reward:.2f}** |"
                    )
            lines.append("")

        return "\n".join(lines)

    # ─── 数据转换 ───

    def constraint_to_rule_result(self, cr: ConstraintResult) -> dict[str, Any]:
        """将 ConstraintResult 转为 rule_results.json 条目格式。"""
        entry: dict[str, Any] = {
            "rule_id": cr.constraint_id,
            "constraint_id": cr.constraint_id,
            "name": cr.name,
            "tier": cr.tier.value,
            "passed": cr.status == EvalStatus.PASS,
            "score": cr.score,
            "reason": cr.reason,
            "details": cr.details,
            "duration_ms": cr.duration_ms,
        }
        # LLM Judge 溯源字段
        if cr.judge_provider is not None:
            entry["judge_provider"] = cr.judge_provider
        if cr.judge_model is not None:
            entry["judge_model"] = cr.judge_model
        if cr.judge_record_path is not None:
            entry["judge_record_path"] = cr.judge_record_path
        # 目录模式模块结果
        if cr.module_results is not None:
            entry["module_results"] = cr.module_results
        return entry

    def sample_to_rule_results(self, sample_result: SampleResult) -> list[dict[str, Any]]:
        """将 SampleResult 的所有约束结果扁平化为 rule_results.json 列表。"""
        results: list[dict[str, Any]] = []
        for stage_result in sample_result.stage_results.values():
            for cr in stage_result.constraint_results:
                results.append(self.constraint_to_rule_result(cr))
        return results
