"""JUnit XML 渲染器测试（requirement/06 FR-1）。"""

from __future__ import annotations

import xml.dom.minidom
import xml.etree.ElementTree as ET

from agent_eval.evaluation.models import MetricsReport
from agent_eval.reporting.gate import evaluate_gate
from agent_eval.reporting.junit_renderer import render_junit_xml

_OFF_GATE = {
    "mode": "off",
    "enabled": False,
    "passed": True,
    "failures": [],
    "failed_metrics": [],
}


def _report(
    metrics: dict[str, float] | None = None,
    thresholds: dict[str, dict] | None = None,
    sample_scores: list[dict] | None = None,
) -> MetricsReport:
    return MetricsReport(
        run_id="20260914_135901",
        total_samples=2,
        metrics=metrics if metrics is not None else {"edu:reward": 4.5},
        thresholds=thresholds if thresholds is not None else {},
        sample_scores=sample_scores
        if sample_scores is not None
        else [{"sample_id": "task_001", "reward": 4.5}],
    )


class TestWellFormed:
    """良构性与计数。"""

    def test_minidom_parseable(self) -> None:
        """xml.dom.minidom 可解析（验收 #2）。"""
        xml_str = render_junit_xml(_report(), _OFF_GATE, "edu")
        doc = xml.dom.minidom.parseString(xml_str)
        assert doc.documentElement.tagName == "testsuites"

    def test_has_xml_declaration(self) -> None:
        xml_str = render_junit_xml(_report(), _OFF_GATE, "edu")
        assert xml_str.startswith('<?xml version="1.0" encoding="UTF-8"?>')

    def test_root_counts(self) -> None:
        """根 tests = 指标数 + 样本数（验收 #2）。"""
        report = _report(
            metrics={"edu:reward": 4.5, "edu:coverage": 0.8},
            sample_scores=[
                {"sample_id": "task_001", "reward": 4.5},
                {"sample_id": "task_002", "reward": 3.0},
            ],
        )
        root = ET.fromstring(render_junit_xml(report, _OFF_GATE, "edu"))
        assert root.get("tests") == "4"  # 2 指标 + 2 样本
        assert root.get("failures") == "0"
        assert root.get("errors") == "0"

    def test_suite_counts_match_failure_elements(self) -> None:
        """failures 计数与实际 <failure> 元素数一致（验收 #2）。"""
        report = _report(
            thresholds={"edu:reward": {"threshold": 7.0}},
            sample_scores=[
                {"sample_id": "task_001", "reward": 4.5},
                {"sample_id": "task_002"},  # 无 reward → 恒失败
            ],
        )
        gate = dict(evaluate_gate(report, "strict"))
        root = ET.fromstring(render_junit_xml(report, gate, "edu"))
        failures_attr = int(root.get("failures", "0"))
        elements = root.findall(".//failure")
        assert failures_attr == len(elements) == 2  # 1 门禁失败 + 1 缺 reward


class TestMetricsSuite:
    """metrics 套件用例映射。"""

    def test_case_per_metric_with_classname(self) -> None:
        report = _report(metrics={"edu:reward": 4.5, "edu:coverage": 0.8})
        root = ET.fromstring(render_junit_xml(report, _OFF_GATE, "edu"))
        suite = root.find("testsuite[@name='metrics']")
        cases = suite.findall("testcase")
        assert [c.get("name") for c in cases] == ["edu:reward", "edu:coverage"]
        assert all(c.get("classname") == "edu.metrics" for c in cases)

    def test_gate_off_all_pass(self) -> None:
        """门禁关闭：指标用例全过，无 <failure>（验收 #3）。"""
        report = _report(
            metrics={"edu:reward": 0.1},
            thresholds={"edu:reward": {"threshold": 7.0}},
        )
        root = ET.fromstring(render_junit_xml(report, _OFF_GATE, "edu"))
        assert root.findall(".//failure") == []

    def test_gate_failure_message_is_original_text(self) -> None:
        """失败用例 message = 门禁失败原文（验收 #4）。"""
        report = _report(thresholds={"edu:reward": {"threshold": 7.0}})
        gate = evaluate_gate(report, "strict")
        root = ET.fromstring(render_junit_xml(report, gate, "edu"))
        failure = root.find(".//testcase[@name='edu:reward']/failure")
        assert failure is not None
        assert failure.get("message") == "edu:reward=4.5 < 阈值7.0"
        assert failure.get("type") == "GateFailure"

    def test_system_out_carries_value_and_threshold(self) -> None:
        report = _report(thresholds={"edu:reward": {"threshold": 7.0}})
        root = ET.fromstring(render_junit_xml(report, _OFF_GATE, "edu"))
        out = root.find(".//testcase[@name='edu:reward']/system-out")
        assert "metric: edu:reward" in out.text
        assert "value: 4.5" in out.text
        assert "threshold(>=): 7.0" in out.text


class TestSamplesSuite:
    """samples 套件用例映射。"""

    def test_missing_reward_fails_regardless_of_gate(self) -> None:
        """样本缺 reward → 恒失败，无论门禁开关（验收 #6）。"""
        report = _report(
            sample_scores=[{"sample_id": "task_002"}],
        )
        root = ET.fromstring(render_junit_xml(report, _OFF_GATE, "edu"))
        failure = root.find(".//testcase[@name='task_002']/failure")
        assert failure is not None
        assert failure.get("type") == "MissingScore"
        assert "无 reward 得分" in failure.get("message")

    def test_sample_with_reward_passes(self) -> None:
        report = _report(sample_scores=[{"sample_id": "task_001", "reward": 4.5}])
        root = ET.fromstring(render_junit_xml(report, _OFF_GATE, "edu"))
        tc = root.find(".//testcase[@name='task_001']")
        assert tc.find("failure") is None

    def test_system_out_carries_scores_json(self) -> None:
        """样本用例 system-out 携带得分明细 JSON。"""
        scores = {"sample_id": "task_001", "reward": 4.5, "soft": 0.9}
        root = ET.fromstring(render_junit_xml(_report(sample_scores=[scores]), _OFF_GATE, "edu"))
        out = root.find(".//testcase[@name='task_001']/system-out")
        assert '"soft": 0.9' in out.text


class TestEscaping:
    """XML 转义。"""

    def test_special_chars_escaped(self) -> None:
        """属性/文本中的 <>&'" 由 ET 自动转义，产物保持良构。"""
        report = _report(
            sample_scores=[{"sample_id": 'task<"&">1', "reward": 1.0}],
        )
        xml_str = render_junit_xml(report, _OFF_GATE, "edu")
        root = ET.fromstring(xml_str)  # 不抛 ParseError 即良构
        tc = root.find(".//testcase[@name='task<\"&\">1']")
        assert tc is not None


class TestProperties:
    """run_id / package_id 属性。"""

    def test_root_and_suite_properties(self) -> None:
        root = ET.fromstring(render_junit_xml(_report(), _OFF_GATE, "edu"))
        for elem in [root, *root.findall("testsuite")]:
            props = {p.get("name"): p.get("value") for p in elem.findall("properties/property")}
            assert props["run_id"] == "20260914_135901"
            assert props["package_id"] == "edu"

    def test_run_url_property_on_root_only(self) -> None:
        """run_url 只进根 properties（run 级信息）；不传时无该属性。"""
        root = ET.fromstring(
            render_junit_xml(
                _report(), _OFF_GATE, "edu", run_url="https://p.example.com/run/20260914_135901"
            )
        )
        props = {p.get("name"): p.get("value") for p in root.findall("properties/property")}
        assert props["run_url"] == "https://p.example.com/run/20260914_135901"
        for su in root.findall("testsuite"):
            names = {p.get("name") for p in su.findall("properties/property")}
            assert "run_url" not in names
        bare = ET.fromstring(render_junit_xml(_report(), _OFF_GATE, "edu"))
        assert "run_url" not in {p.get("name") for p in bare.findall("properties/property")}
