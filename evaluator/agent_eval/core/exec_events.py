"""执行事件埋点 — verbose 档过程事件行的事件源。

三类事件：SUT 请求/响应摘要（方法/端点/状态码/耗时）、judge 交互（评估器/结论/
耗时）、重试事件。埋点原则：**只加事件、不改指标逻辑**——emit 是旁路日志，
失败不影响主流程（标准库 logging 已吞渲染异常）。

事件走独立日志器（``agent_eval.exec``，propagate=False）：normal/quiet 档静默
丢弃，verbose/debug 档由 ``core.logging.install_exec_event_handler`` 挂渲染器
直出 stderr（见 core/logging.py 隔离说明）。
"""

from __future__ import annotations

import logging

EXEC_EVENT_LOGGER = "agent_eval.exec"


def _emit(message: str) -> None:
    logging.getLogger(EXEC_EVENT_LOGGER).info(message)


def _fmt_ms(elapsed_ms: float | None) -> str:
    if elapsed_ms is None:
        return ""
    return f"（{elapsed_ms:.0f}ms）" if elapsed_ms < 1000 else f"（{elapsed_ms / 1000:.1f}s）"


def sut_request(
    *,
    method: str,
    url: str,
    status: int | None = None,
    elapsed_ms: float | None = None,
    replayed: bool = False,
    error: str | None = None,
) -> None:
    """SUT 请求/响应摘要（两条通道共用咽喉 SUTChannel.request 埋点）。"""
    target = url if len(url) <= 120 else url[:117] + "…"
    if error is not None:
        _emit(f"SUT {method} {target} ✗ {error}{_fmt_ms(elapsed_ms)}")
        return
    suffix = "（凭证重登重放）" if replayed else ""
    _emit(f"SUT {method} {target} → {status}{_fmt_ms(elapsed_ms)}{suffix}")


def judge_evaluated(
    *,
    evaluator: str,
    status: str,
    score: float | None = None,
    elapsed_ms: float = 0.0,
) -> None:
    """judge 交互（评估器/结论/耗时；rule 与 LLM 判官同点埋——PipelineStage）。"""
    score_part = f"，score={score:.2f}" if score is not None else ""
    _emit(f"判官 {evaluator}：{status}{score_part}{_fmt_ms(elapsed_ms)}")


def retry(*, what: str, detail: str) -> None:
    """重试事件（judge 解析重试、通道自动重登等）。"""
    _emit(f"重试 {what}：{detail}")
