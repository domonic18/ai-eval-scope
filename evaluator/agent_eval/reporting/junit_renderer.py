"""JUnit XML 渲染器（requirement/06 FR-1）。

从内存 MetricsReport 直接渲染（与 schema 同源同版本，禁止从 summary.json
反序列化再渲染——杜绝版本错位），供 CI 的 junit 步骤原生消费
（Jenkins/GitLab/CircleCI 均支持）。

用例映射（语义已经消费方参考实现验证）：

- ``metrics`` 套件：每指标一条用例，失败 = 该指标 ∈ 门禁 failed_metrics
  （门禁关闭时全过，只报值不断结果）；
- ``samples`` 套件：每样本一条用例，失败 = sample_scores 中该样本 reward 缺失
  （执行或判分未产出，无论门禁开关恒失败——异常必须显形）。

纯标准库（xml.etree.ElementTree），零新增第三方依赖（NF-1）。
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from typing import Any

from agent_eval.evaluation.models import MetricsReport

_XML_DECLARATION = '<?xml version="1.0" encoding="UTF-8"?>\n'


def _failures_by_metric(gate: dict[str, Any]) -> dict[str, str]:
    """门禁失败原文按指标 id 归位（failure 形如 ``mid=值 < 阈值t``）。"""
    return {f.split("=", 1)[0]: f for f in (gate.get("failures") or []) if "=" in f}


def _add_properties(parent: ET.Element, run_id: str, package_id: str, run_url: str = "") -> None:
    props = ET.SubElement(parent, "properties")
    ET.SubElement(props, "property", name="run_id", value=run_id)
    ET.SubElement(props, "property", name="package_id", value=package_id)
    if run_url:
        ET.SubElement(props, "property", name="run_url", value=run_url)


def render_junit_xml(
    report: MetricsReport,
    gate: dict[str, Any],
    package_id: str,
    run_url: str = "",
) -> str:
    """渲染 JUnit XML 字符串（UTF-8，带 xml declaration）。

    Args:
        report: 内存 MetricsReport（metrics / sample_scores / thresholds）。
        gate: :func:`~agent_eval.reporting.gate.evaluate_gate` 输出的 gate 对象。
        package_id: 场景包 id（classname 前缀，如 ``edu``）。
        run_url: 平台运行详情页地址（根节点 properties；上报未开启时为空）。
    """
    run_id = report.run_id or "unknown"
    failed_metrics = set(gate.get("failed_metrics") or [])
    failure_msg = _failures_by_metric(gate)

    root = ET.Element("testsuites", name=f"agent-eval {run_id}")
    _add_properties(root, run_id, package_id, run_url=run_url)
    suites: list[ET.Element] = []

    # ── metrics 套件：每指标一条用例，值/阈值写 system-out ───────────────
    su = ET.SubElement(root, "testsuite", name="metrics")
    _add_properties(su, run_id, package_id)
    suites.append(su)
    for mid, value in report.metrics.items():
        tc = ET.SubElement(
            su,
            "testcase",
            name=str(mid),
            classname=f"{package_id}.metrics",
        )
        declared = report.thresholds.get(mid)
        threshold = declared.get("threshold") if isinstance(declared, dict) else declared
        lines = [f"metric: {mid}", f"value: {value}"]
        if threshold is not None:
            lines.append(f"threshold(>=): {threshold}")
        ET.SubElement(tc, "system-out").text = "\n".join(lines)
        if mid in failed_metrics:
            ET.SubElement(
                tc,
                "failure",
                type="GateFailure",
                message=failure_msg.get(mid, f"{mid} 未达标"),
            )

    # ── samples 套件：每样本一条用例，无 reward 即失败（恒生效）─────────
    su = ET.SubElement(root, "testsuite", name="samples")
    _add_properties(su, run_id, package_id)
    suites.append(su)
    for item in report.sample_scores:
        if not isinstance(item, dict):
            continue
        sid = str(item.get("sample_id") or "unknown")
        reward = item.get("reward")
        tc = ET.SubElement(
            su,
            "testcase",
            name=sid,
            classname=f"{package_id}.samples",
        )
        detail = json.dumps(item, ensure_ascii=False, indent=2)
        ET.SubElement(tc, "system-out").text = f"sample: {sid}\nreward: {reward}\nscores: {detail}"
        if reward is None:
            ET.SubElement(
                tc,
                "failure",
                type="MissingScore",
                message=f"样本 {sid} 无 reward 得分（执行或判分未产出）",
            )

    # ── 计数（根与各 suite 均须准确，Jenkins 趋势页依赖）────────────────
    total = fails = 0
    for suite in suites:
        cases = suite.findall("testcase")
        n_fail = sum(1 for tc in cases if tc.find("failure") is not None)
        suite.set("tests", str(len(cases)))
        suite.set("failures", str(n_fail))
        suite.set("errors", "0")
        suite.set("skipped", "0")
        suite.set("time", "0")
        total += len(cases)
        fails += n_fail
    root.set("tests", str(total))
    root.set("failures", str(fails))
    root.set("errors", "0")

    tree = ET.ElementTree(root)
    if hasattr(ET, "indent"):  # Python 3.9+；缩进仅为人类可读
        ET.indent(tree, space="  ")
    return _XML_DECLARATION + ET.tostring(root, encoding="unicode")
