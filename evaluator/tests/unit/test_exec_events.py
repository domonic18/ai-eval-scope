"""core/exec_events 事件消息格式的单元测试（arch/15 §4.4，Sprint 14a）。

渲染行为（handler 挂载/静默）归 test_logging.py；此处只验三类事件的
消息形态——verbose 档 stderr 直出行的人类可读契约。
"""

from __future__ import annotations

import logging

import pytest

from agent_eval.core.exec_events import EXEC_EVENT_LOGGER, judge_evaluated, retry, sut_request


@pytest.fixture
def _capture():
    """挂临时 handler 捕获事件消息（渲染器行为无关，直接捕 logger 输出）。"""
    records: list[str] = []

    class _List(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record.getMessage())

    handler = _List()
    logger = logging.getLogger(EXEC_EVENT_LOGGER)
    logger.addHandler(handler)
    yield records
    logger.removeHandler(handler)


def test_sut_request_success_line(_capture) -> None:
    """成功响应：方法 端点 → 状态码（耗时）。"""
    sut_request(
        method="POST", url="https://sut.example.com/api/agent", status=200, elapsed_ms=312.4
    )
    assert _capture == ["SUT POST https://sut.example.com/api/agent → 200（312ms）"]


def test_sut_request_replay_and_slow_elapsed(_capture) -> None:
    """重放标记与秒级耗时换算。"""
    sut_request(
        method="GET",
        url="https://sut.example.com/x",
        status=200,
        elapsed_ms=1500.0,
        replayed=True,
    )
    assert _capture == ["SUT GET https://sut.example.com/x → 200（1.5s）（凭证重登重放）"]


def test_sut_request_error_line(_capture) -> None:
    """连接失败：✗ + 错误摘要，无状态码。"""
    sut_request(method="POST", url="https://sut.example.com/api", error="ConnectTimeout")
    assert _capture == ["SUT POST https://sut.example.com/api ✗ ConnectTimeout"]


def test_sut_request_long_url_truncated(_capture) -> None:
    """超长 URL 截断至 120 字符（长查询串不淹没事件行）。"""
    sut_request(method="GET", url="https://sut.example.com/" + "a" * 300, status=200)
    (line,) = _capture
    assert len(line) < 200
    assert line.endswith("… → 200")


def test_judge_evaluated_line(_capture) -> None:
    """judge 交互：评估器：结论（score，耗时）。"""
    judge_evaluated(evaluator="内容正确性", status="fail", score=0.4, elapsed_ms=1823.0)
    assert _capture == ["判官 内容正确性：fail，score=0.40（1.8s）"]


def test_judge_evaluated_without_score(_capture) -> None:
    """无分评估器（ERROR 短路等）省略 score 段。"""
    judge_evaluated(evaluator="fmt", status="error", elapsed_ms=2.0)
    assert _capture == ["判官 fmt：error（2ms）"]


def test_retry_line(_capture) -> None:
    """重试事件：对象 + 缘由。"""
    retry(what="判官输出解析", detail="content_verdict 第 2 次尝试解析失败，重试")
    assert _capture == ["重试 判官输出解析：content_verdict 第 2 次尝试解析失败，重试"]
