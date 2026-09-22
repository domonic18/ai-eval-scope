"""质量门禁判定。

三态语义：

- ``off``（默认）：不判定，仅出报告；
- ``strict``：逐项卡点——MetricsReport.thresholds 中声明了 threshold 的每个指标，
  值 ≥ threshold 方为通过，未声明阈值的指标不参与判定；
- ``<float>``：综合得分卡点——所有 reward 指标（id 为 ``reward`` 或 ``*:reward``）
  值 ≥ float 方为通过，与指标同量纲直接比较（不做归一化假设）。

配置错误（阈值不可解析 / float 模式无 reward 指标）抛 :class:`GateConfigError`，
由 CLI 映射为退出码 1；门禁未达标映射为退出码 3。
"""

from __future__ import annotations

from typing import Any

from agent_eval.core.exceptions import GateConfigError
from agent_eval.evaluation.models import MetricsReport

# 门禁关闭（"0" 兼容消费方历史传参习惯）
_OFF_SPECS = ("", "off", "0")


def normalize_gate(raw: str | None) -> str:
    """归一门禁取值：返回 "off" / "strict" / float 字符串。

    非法取值抛 :class:`GateConfigError`（语法校验，可在执行前 fail fast）。
    """
    spec = (raw or "off").strip().lower()
    if spec in _OFF_SPECS:
        return "off"
    if spec == "strict":
        return "strict"
    try:
        float(spec)
    except ValueError:
        raise GateConfigError(
            f"--gate 取值不可解析: {raw!r}（应为 off / strict / 小数阈值）",
        ) from None
    return spec


def _declared_thresholds(report: MetricsReport) -> dict[str, float]:
    """提取声明阈值快照（key=metric_id）：兼容 {"threshold": t} 与裸值两种形态。"""
    out: dict[str, float] = {}
    for mid, th in report.thresholds.items():
        value = th.get("threshold") if isinstance(th, dict) else th
        if value is not None:
            out[mid] = float(value)
    return out


def reward_metric_ids(metrics: dict[str, float]) -> list[str]:
    """reward 指标 id：id 为 ``reward`` 或以 ``:reward`` 结尾（如 ``edu:reward``）。"""
    return [k for k in metrics if k == "reward" or k.endswith(":reward")]


def evaluate_gate(report: MetricsReport, gate: str = "off") -> dict[str, Any]:
    """按三态语义判定门禁，返回 summary.json 顶层 ``gate`` 对象。

    Returns:
        {"mode", "enabled", "passed", "failures", "failed_metrics"}

    Raises:
        GateConfigError: float 模式下指标中无 reward（配置错误）。
    """
    spec = normalize_gate(gate)
    if spec == "off":
        return {
            "mode": "off",
            "enabled": False,
            "passed": True,
            "failures": [],
            "failed_metrics": [],
        }

    failures: list[str] = []
    failed_metrics: list[str] = []

    if spec == "strict":
        # 逐项卡点：声明了阈值的指标，值缺失或低于阈值均失败（异常必须显形）
        for mid, threshold in _declared_thresholds(report).items():
            value = report.metrics.get(mid)
            if value is None or float(value) < threshold:
                failures.append(f"{mid}={value} < 阈值{threshold}")
                failed_metrics.append(mid)
    else:
        # 综合得分卡点：同量纲直接比较，无 reward 视为配置错误
        threshold = float(spec)
        reward_keys = reward_metric_ids(report.metrics)
        if not reward_keys:
            raise GateConfigError(
                f"--gate {gate}: 指标中无 reward（综合得分），无法按阈值卡点；改用 strict 或 off",
            )
        for key in reward_keys:
            value = float(report.metrics[key])
            if value < threshold:
                failures.append(f"{key}={value} < {threshold}")
                failed_metrics.append(key)

    return {
        "mode": spec,
        "enabled": True,
        "passed": not failures,
        "failures": failures,
        "failed_metrics": failed_metrics,
    }
