"""ReportGenerator — Markdown + JSON 双格式报告生成。

生成任务级和聚合级两种报告：
- 任务级: 每个评估样本的约束结果、得分、LLM 溯源
- 聚合级: DR/CPR/Reward 指标表、阈值对比、失败项明细
"""

from __future__ import annotations

from typing import Any

from agent_eval.config import METRIC_THRESHOLDS, REPORTING_DEFAULTS
from agent_eval.core.types import EvalStatus
from agent_eval.evaluation.models import (
    ConstraintResult,
    MetricsReport,
    SampleResult,
)

# 默认阈值（集中维护于 agent_eval.config.evaluation）
_DEFAULT_THRESHOLDS: dict[str, float] = {
    "DR": METRIC_THRESHOLDS.dr,
    "CPR": METRIC_THRESHOLDS.cpr,
    "avg_reward": METRIC_THRESHOLDS.avg_reward,
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
                lines.append(
                    f"| {cr.name} | {tier_mark} | {status_icon} | {cr.score:.2f} | {cr.reason} |"
                )

            lines.append("")

            # 约束详情 — 展示 details 中的检查信息
            details_sections: list[tuple[str, ConstraintResult]] = []
            for cr in stage_result.constraint_results:
                if cr.details:
                    details_sections.append((cr.name, cr))

            if details_sections:
                lines.append("<details>")
                lines.append("<summary>📋 检查详情</summary>")
                lines.append("")
                for name, cr in details_sections:
                    lines.append(f"**{name}**")
                    lines.append("")
                    self._render_details_block(lines, cr.details)
                lines.append("</details>")
                lines.append("")

            # LLM Judge 评审详情
            llm_results = [
                cr for cr in stage_result.constraint_results if cr.judge_provider is not None
            ]
            if llm_results:
                lines.append("### LLM Judge 评审")
                lines.append("")
                for cr in llm_results:
                    lines.append(f"**{cr.name}** ({cr.score:.2f})")
                    lines.append(f"- Provider: `{cr.judge_provider}` / `{cr.judge_model}`")
                    # 展示维度详情
                    dims = cr.details.get("dimensions", []) if cr.details else []
                    if dims:
                        for d in dims:
                            conf_icon = "🟢" if d.get("confidence") == "high" else "🟡"
                            lines.append(
                                f"- {conf_icon} {d['name']}: {d['score']:.1f}/10"
                                f" (权重 {d['weight']:.0%}, {d['confidence']})"
                            )
                    # 展示 LLM 评价总结
                    summary = cr.details.get("summary", "") if cr.details else ""
                    if summary:
                        lines.append(f"> {summary[:300]}")
                    if cr.judge_record_path:
                        lines.append(f"- 溯源记录: `{cr.judge_record_path}`")
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

    def _render_details_block(self, lines: list[str], details: dict[str, Any]) -> None:
        """将 details dict 渲染为 Markdown 列表。"""
        # 优先展示的关键字段（按顺序）
        _DETAIL_KEYS = [
            ("checked_files", "检查文件"),
            ("valid_files", "有效文件"),
            ("files", "文件列表"),
            ("files_checked", "检查文件"),
            ("invalid_files", "无效文件"),
            ("issues", "问题"),
            ("errors", "错误"),
            ("score_breakdown", "得分明细"),
            ("heading_summary", "标题结构"),
            ("checks", "检查项"),
            ("screenshot_paths", "视觉截图"),
        ]

        rendered_keys: set[str] = set()

        for key, label in _DETAIL_KEYS:
            if key not in details:
                continue
            value = details[key]
            rendered_keys.add(key)

            if isinstance(value, list):
                if not value:
                    continue
                # 列表类字段
                if key in (
                    "checked_files",
                    "valid_files",
                    "files",
                    "files_checked",
                    "screenshot_paths",
                ):
                    # 文件/截图列表：紧凑显示
                    if len(value) <= REPORTING_DEFAULTS.summary_list_max_items:
                        lines.append(
                            f"- {label}（{len(value)} 个）: {', '.join(str(v) for v in value)}"
                        )
                    else:
                        lines.append(
                            f"- {label}（{len(value)} 个）: {', '.join(str(v) for v in value[: REPORTING_DEFAULTS.summary_list_max_items])} ...等 {len(value)} 个"
                        )
                elif key in ("invalid_files", "issues", "errors"):
                    # 错误/问题列表：逐条显示
                    lines.append(f"- {label}（{len(value)} 项）:")
                    for item in value[: REPORTING_DEFAULTS.error_list_max_items]:
                        parsed = self._parse_error_item(item)
                        if parsed:
                            lines.append(f"  - **文件**: `{parsed['file']}`")
                            lines.append(f"    - **错误内容**: `{parsed['content']}`")
                            lines.append(f"    - **解释说明**: {parsed['explanation']}")
                        else:
                            lines.append(f"  - {item}")
                    if len(value) > REPORTING_DEFAULTS.error_list_max_items:
                        lines.append(f"  - ... 共 {len(value)} 项")
                elif key == "checks":
                    lines.append(f"- {label}:")
                    for item in value:
                        if isinstance(item, dict):
                            icon = "✅" if item.get("passed") else "❌"
                            lines.append(
                                f"  - {icon} {item.get('name', '?')}: {item.get('reason', '')}"
                            )
                        else:
                            lines.append(f"  - {item}")
                else:
                    lines.append(f"- {label}: {value}")
            elif isinstance(value, dict):
                if key == "score_breakdown":
                    lines.append(f"- {label}:")
                    for k, v in value.items():
                        lines.append(
                            f"  - {k}: {v:.3f}" if isinstance(v, float) else f"  - {k}: {v}"
                        )
                elif key == "heading_summary":
                    lines.append(f"- {label}:")
                    for fname, headings in value.items():
                        if isinstance(headings, list) and headings:
                            heading_strs = [
                                f"H{h[0]}: {h[1][:30]}"
                                for h in headings[: REPORTING_DEFAULTS.heading_summary_max_items]
                            ]
                            lines.append(f"  - {fname}: {', '.join(heading_strs)}")
                else:
                    lines.append(f"- {label}: {value}")
            else:
                lines.append(f"- {label}: {value}")

        # 渲染剩余未特殊处理的字段
        for key, value in details.items():
            if key in rendered_keys:
                continue
            if isinstance(value, (str, int, float, bool)):
                lines.append(f"- {key}: {value}")
            elif (
                isinstance(value, list) and len(value) <= REPORTING_DEFAULTS.summary_list_max_items
            ):
                lines.append(f"- {key}: {value}")
            elif isinstance(value, list):
                lines.append(f"- {key}: [{len(value)} 项]")

        lines.append("")

    def _parse_error_item(self, item: Any) -> dict[str, str] | None:
        """解析公式/算术错误条目，提取文件、错误内容、解释说明。

        预期格式："文件路径: 错误类型 表达式（应为 xxx）"
        """
        if not isinstance(item, str):
            return None
        import re

        match = re.match(r"^(.+?):\s*(.+?)\s*（应为\s*(.+?)）$", item)
        if match:
            return {
                "file": match.group(1).strip(),
                "content": match.group(2).strip(),
                "explanation": f"正确结果应为 {match.group(3).strip()}",
            }
        return None

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
