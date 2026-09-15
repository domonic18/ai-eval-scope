"""报告生成 — Markdown + JSON 双格式报告 + CI 集成（JUnit XML / 纯文本摘要 / 门禁）。"""

from agent_eval.reporting.gate import evaluate_gate, normalize_gate
from agent_eval.reporting.junit_renderer import render_junit_xml
from agent_eval.reporting.report_generator import ReportGenerator
from agent_eval.reporting.summary_text import render_summary_txt

__all__ = [
    "ReportGenerator",
    "evaluate_gate",
    "normalize_gate",
    "render_junit_xml",
    "render_summary_txt",
]
