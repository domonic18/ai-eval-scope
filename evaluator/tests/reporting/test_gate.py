"""质量门禁三态判定测试（requirement/06 FR-3）。"""

from __future__ import annotations

import pytest

from agent_eval.core.exceptions import GateConfigError
from agent_eval.evaluation.models import MetricsReport
from agent_eval.reporting.gate import evaluate_gate, normalize_gate


def _report(
    metrics: dict[str, float] | None = None,
    thresholds: dict[str, dict] | None = None,
) -> MetricsReport:
    return MetricsReport(
        run_id="20260914_135901",
        total_samples=2,
        metrics=metrics or {"edu:reward": 4.5, "edu:coverage": 0.8},
        thresholds=thresholds or {"edu:reward": {"threshold": 7.0, "unit": "score"}},
    )


class TestNormalizeGate:
    """门禁取值归一化。"""

    @pytest.mark.parametrize("raw", [None, "", "off", "OFF", "0"])
    def test_off_forms(self, raw: str | None) -> None:
        """None/空串/off/字符串零均归一为 off（验收 #7）。"""
        assert normalize_gate(raw) == "off"

    def test_strict(self) -> None:
        assert normalize_gate("strict") == "strict"

    def test_float(self) -> None:
        assert normalize_gate("8.0") == "8.0"

    def test_invalid_raises(self) -> None:
        with pytest.raises(GateConfigError, match="不可解析"):
            normalize_gate("abc")


class TestGateOff:
    """门禁关闭语义。"""

    def test_off_no_judgement(self) -> None:
        gate = evaluate_gate(_report(), "off")
        assert gate == {
            "mode": "off",
            "enabled": False,
            "passed": True,
            "failures": [],
            "failed_metrics": [],
        }

    def test_zero_string_is_off(self) -> None:
        """--gate 0（字符串零）按 off 处理（验收 #7）。"""
        assert evaluate_gate(_report(), "0")["enabled"] is False


class TestGateStrict:
    """strict 逐项声明阈值卡点。"""

    def test_below_threshold_fails(self) -> None:
        """值 < 声明阈值 → 失败，原文含 阈值 前缀（验收 #4）。"""
        gate = evaluate_gate(_report(), "strict")
        assert gate["enabled"] is True
        assert gate["passed"] is False
        assert gate["failed_metrics"] == ["edu:reward"]
        assert gate["failures"] == ["edu:reward=4.5 < 阈值7.0"]

    def test_pass_when_all_above(self) -> None:
        report = _report(
            metrics={"edu:reward": 8.0},
            thresholds={"edu:reward": {"threshold": 7.0}},
        )
        gate = evaluate_gate(report, "strict")
        assert gate["passed"] is True
        assert gate["failures"] == []

    def test_missing_value_fails(self) -> None:
        """声明了阈值但指标缺失 → 也算失败（异常显形）。"""
        report = _report(metrics={"edu:coverage": 0.8})
        gate = evaluate_gate(report, "strict")
        assert gate["passed"] is False
        assert gate["failed_metrics"] == ["edu:reward"]

    def test_undeclared_metric_not_judged(self) -> None:
        """未声明阈值的指标不参与判定。"""
        report = _report(
            metrics={"edu:reward": 8.0, "edu:low": 0.0},
            thresholds={"edu:reward": {"threshold": 7.0}},
        )
        gate = evaluate_gate(report, "strict")
        assert gate["passed"] is True
        assert gate["failed_metrics"] == []

    def test_multi_failure(self) -> None:
        report = _report(
            metrics={"a:reward": 1.0, "b:reward": 2.0},
            thresholds={
                "a:reward": {"threshold": 7.0},
                "b:reward": {"threshold": 7.0},
            },
        )
        gate = evaluate_gate(report, "strict")
        assert gate["failed_metrics"] == ["a:reward", "b:reward"]


class TestGateFloat:
    """<float> reward 综合得分卡点。"""

    def test_reward_below_threshold_fails(self) -> None:
        """reward 4.5 配阈值 8.0 → 卡住（验收 #5，同量纲直接比较）。"""
        gate = evaluate_gate(_report(), "8.0")
        assert gate["enabled"] is True
        assert gate["passed"] is False
        assert gate["failed_metrics"] == ["edu:reward"]
        assert gate["failures"] == ["edu:reward=4.5 < 8.0"]

    def test_reward_above_passes(self) -> None:
        assert evaluate_gate(_report(), "4.0")["passed"] is True

    def test_bare_reward_key(self) -> None:
        """无场景前缀的裸 ``reward`` 指标同样参与卡点。"""
        report = _report(metrics={"reward": 3.0})
        gate = evaluate_gate(report, "5.0")
        assert gate["failed_metrics"] == ["reward"]

    def test_no_reward_is_config_error(self) -> None:
        """float 模式无 reward 指标 → GateConfigError（exit 1）。"""
        report = _report(metrics={"edu:coverage": 0.8}, thresholds={})
        with pytest.raises(GateConfigError, match="无 reward"):
            evaluate_gate(report, "8.0")

    def test_multi_reward_all_judged(self) -> None:
        report = _report(metrics={"edu:reward": 8.0, "code:reward": 3.0})
        gate = evaluate_gate(report, "5.0")
        assert gate["failed_metrics"] == ["code:reward"]
