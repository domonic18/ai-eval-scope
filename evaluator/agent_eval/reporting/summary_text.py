"""纯文本摘要渲染器（requirement/06 FR-2）。

CI 的 Groovy 层在沙箱约束下无法解析 JSON（CPS 序列化 + 脚本白名单），
纯文本是唯一可靠通道——工具输出后，消费方 CI 只需 ``readFile`` + ``echo``。

产物 ``reports/summary.txt`` 两部分：

- **首行**（固定格式，CI 直接取作构建描述，如 Jenkins ``currentBuild.description``）：
  ``run <run_id> · <N> 样本 · <结论标记><得分> · agent-eval <版本>``；
- **控制台块**（CI 直接 ``cat`` 进构建日志）：评测 Run / 样本总数 / 指标概览 /
  门禁结论 / 未达标项。
"""

from __future__ import annotations

from typing import Any

from agent_eval.evaluation.models import MetricsReport
from agent_eval.reporting.gate import reward_metric_ids

_SEPARATOR = "=" * 40
_GATE_LINE_OFF = "⏸ 已关闭（--gate off，仅出报告）"


def _gate_line(gate: dict[str, Any]) -> str:
    """门禁结论文案：✅ 通过 | ❌ 未通过 | ⏸ 已关闭。"""
    if not gate.get("enabled"):
        return _GATE_LINE_OFF
    return "✅ 通过" if gate.get("passed") else "❌ 未通过"


def _first_line(report: MetricsReport, gate: dict[str, Any], tool_version: str) -> str:
    """单行摘要（机器截取：段间 ``·`` 分隔，门禁关闭不留多余空格）。"""
    segments = [f"run {report.run_id}", f"{report.total_samples} 样本"]
    mark = ""
    if gate.get("enabled"):
        mark = "✅" if gate.get("passed") else "❌"
    reward_keys = reward_metric_ids(report.metrics)
    score_txt = f" {report.metrics[reward_keys[0]]:.2f}" if reward_keys else ""
    tail = f"{mark}{score_txt}".strip()
    if tail:
        segments.append(tail)
    segments.append(f"agent-eval {tool_version}")
    return " · ".join(segments)


def render_summary_txt(
    report: MetricsReport,
    gate: dict[str, Any],
    tool_version: str,
) -> str:
    """渲染纯文本摘要（首行 + 控制台块）。

    Args:
        report: 内存 MetricsReport。
        gate: :func:`~agent_eval.reporting.gate.evaluate_gate` 输出的 gate 对象。
        tool_version: 工具自身版本（``agent_eval.__version__``）。
    """
    lines = [
        _first_line(report, gate, tool_version),
        _SEPARATOR,
        f"评测 Run:     {report.run_id}",
        f"样本总数:     {report.total_samples}",
        "指标概览:",
    ]
    for mid, value in report.metrics.items():
        declared = report.thresholds.get(mid)
        threshold = declared.get("threshold") if isinstance(declared, dict) else declared
        note = f"（阈值 ≥ {threshold}）" if threshold is not None else ""
        lines.append(f"  {mid} = {value}{note}")
    lines.append(f"门禁结论:     {_gate_line(gate)}")
    failures = gate.get("failures") or []
    lines.append(f"未达标项:     {'；'.join(failures) if failures else '无'}")
    lines.append(_SEPARATOR)
    return "\n".join(lines) + "\n"
