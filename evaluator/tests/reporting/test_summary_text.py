"""纯文本摘要渲染器测试（requirement/06 FR-2）。"""

from __future__ import annotations

from agent_eval.evaluation.models import MetricsReport
from agent_eval.reporting.gate import evaluate_gate
from agent_eval.reporting.summary_text import render_summary_txt


def _report(
    metrics: dict[str, float] | None = None,
    thresholds: dict[str, dict] | None = None,
) -> MetricsReport:
    return MetricsReport(
        run_id="20260914_135901",
        total_samples=10,
        metrics=metrics if metrics is not None else {"edu:reward": 4.5},
        thresholds=thresholds or {},
    )


class TestFirstLine:
    """首行单行摘要（CI 构建描述）。"""

    def test_gate_passed(self) -> None:
        gate = {
            "mode": "strict",
            "enabled": True,
            "passed": True,
            "failures": [],
            "failed_metrics": [],
        }
        first = render_summary_txt(_report(), gate, "0.3.2").splitlines()[0]
        assert first == "run 20260914_135901 · 10 样本 · ✅ 4.50 · agent-eval 0.3.2"

    def test_gate_failed(self) -> None:
        gate = {
            "mode": "strict",
            "enabled": True,
            "passed": False,
            "failures": ["edu:reward=4.5 < 阈值7.0"],
            "failed_metrics": ["edu:reward"],
        }
        first = render_summary_txt(_report(), gate, "0.3.2").splitlines()[0]
        assert first == "run 20260914_135901 · 10 样本 · ❌ 4.50 · agent-eval 0.3.2"

    def test_gate_off_no_mark_no_extra_space(self) -> None:
        """门禁关闭：结论标记为空，得分段保留（FR-2 得分独立规则），无多余空格。"""
        gate = {
            "mode": "off",
            "enabled": False,
            "passed": True,
            "failures": [],
            "failed_metrics": [],
        }
        first = render_summary_txt(_report(), gate, "0.3.2").splitlines()[0]
        assert first == "run 20260914_135901 · 10 样本 · 4.50 · agent-eval 0.3.2"
        assert "  " not in first

    def test_no_reward_omits_score_segment(self) -> None:
        """无 reward 指标：得分段整段省略，标记保留。"""
        gate = {
            "mode": "strict",
            "enabled": True,
            "passed": True,
            "failures": [],
            "failed_metrics": [],
        }
        report = _report(metrics={"edu:coverage": 0.8})
        first = render_summary_txt(report, gate, "0.3.2").splitlines()[0]
        assert first == "run 20260914_135901 · 10 样本 · ✅ · agent-eval 0.3.2"


class TestConsoleBlock:
    """控制台友好块。"""

    def test_block_structure(self) -> None:
        gate = {
            "mode": "strict",
            "enabled": True,
            "passed": False,
            "failures": ["edu:reward=4.5 < 阈值7.0"],
            "failed_metrics": ["edu:reward"],
        }
        report = _report(
            metrics={"edu:reward": 4.5, "edu:coverage": 0.8},
            thresholds={"edu:reward": {"threshold": 7.0}},
        )
        text = render_summary_txt(report, gate, "0.3.2")
        assert "========================================" in text
        assert "评测 Run:     20260914_135901" in text
        assert "样本总数:     10" in text
        assert "  edu:reward = 4.5（阈值 ≥ 7.0）" in text
        assert "  edu:coverage = 0.8" in text  # 未声明阈值无注记
        assert "门禁结论:     ❌ 未通过" in text
        assert "未达标项:     edu:reward=4.5 < 阈值7.0" in text

    def test_gate_off_line(self) -> None:
        gate = {
            "mode": "off",
            "enabled": False,
            "passed": True,
            "failures": [],
            "failed_metrics": [],
        }
        text = render_summary_txt(_report(), gate, "0.3.2")
        assert "门禁结论:     ⏸ 已关闭（--gate off，仅出报告）" in text
        assert "未达标项:     无" in text

    def test_gate_passed_line(self) -> None:
        gate = evaluate_gate(_report(), "strict")
        text = render_summary_txt(_report(), gate, "0.3.2")
        assert "门禁结论:     ✅ 通过" in text

    def test_multi_failures_joined_by_chinese_semicolon(self) -> None:
        gate = {
            "mode": "strict",
            "enabled": True,
            "passed": False,
            "failures": ["a:reward=1.0 < 阈值7.0", "b:reward=2.0 < 阈值7.0"],
            "failed_metrics": ["a:reward", "b:reward"],
        }
        text = render_summary_txt(_report(), gate, "0.3.2")
        assert "未达标项:     a:reward=1.0 < 阈值7.0；b:reward=2.0 < 阈值7.0" in text

    def test_ends_with_newline(self) -> None:
        gate = {
            "mode": "off",
            "enabled": False,
            "passed": True,
            "failures": [],
            "failed_metrics": [],
        }
        assert render_summary_txt(_report(), gate, "0.3.2").endswith("\n")

    def test_run_url_line_only_when_provided(self) -> None:
        """平台查看页：上报开启时有「平台报告」行；未开启（空串）整行不渲染。"""
        gate = {
            "mode": "off",
            "enabled": False,
            "passed": True,
            "failures": [],
            "failed_metrics": [],
        }
        assert "平台报告" not in render_summary_txt(_report(), gate, "0.3.2")
        text = render_summary_txt(_report(), gate, "0.3.2", run_url="https://p.example.com/run/r1")
        assert "平台报告:     https://p.example.com/run/r1" in text
