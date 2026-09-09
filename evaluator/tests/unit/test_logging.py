"""core/logging 的单元测试。"""

from __future__ import annotations

import io
import logging
import sys

import pytest

from agent_eval.core.logging import (
    _NOISY_HTTP_LOGGERS,
    _ensure_utf8_streams,
    setup_logging,
)


@pytest.fixture
def _restore_logging():
    """保存并恢复 root 与传输层日志器的全局态（setup_logging 是进程级副作用）。"""
    root = logging.getLogger()
    saved = (root.handlers[:], root.level)
    saved_noisy = {n: logging.getLogger(n).level for n in _NOISY_HTTP_LOGGERS}
    yield
    root.handlers[:] = saved[0]
    root.setLevel(saved[1])
    for name, level in saved_noisy.items():
        logging.getLogger(name).setLevel(level)


def test_ensure_utf8_streams_reconfigures_ascii_stream(monkeypatch):
    """ASCII 编码的 stdout 应被 reconfigure 为 UTF-8（errors=replace）。"""
    ascii_stream = io.TextIOWrapper(io.BytesIO(), encoding="ascii")
    monkeypatch.setattr(sys, "stdout", ascii_stream)

    _ensure_utf8_streams()

    assert sys.stdout.encoding == "utf-8"


def test_ensure_utf8_streams_safe_without_reconfigure(monkeypatch):
    """不支持 reconfigure 的流应被安全跳过，不抛异常。"""

    class _DumbStream:
        encoding = "ascii"

    monkeypatch.setattr(sys, "stdout", _DumbStream())

    _ensure_utf8_streams()  # 不应抛 AttributeError


@pytest.mark.usefixtures("_restore_logging")
def test_setup_logging_demotes_transport_info_at_default_level():
    """缺省 INFO 级：httpx/anthropic 等传输层日志器应压到 WARNING（交互会话降噪）。"""
    setup_logging()

    for name in _NOISY_HTTP_LOGGERS:
        assert logging.getLogger(name).level == logging.WARNING, name


@pytest.mark.usefixtures("_restore_logging")
def test_setup_logging_keeps_transport_logs_at_debug():
    """DEBUG（--verbose 诊断）：传输层日志器回 NOTSET 随根级别，全量放行。"""
    setup_logging("INFO")
    setup_logging("DEBUG")

    for name in _NOISY_HTTP_LOGGERS:
        assert logging.getLogger(name).level == logging.NOTSET, name


@pytest.mark.usefixtures("_restore_logging")
def test_setup_logging_reapplies_on_repeat_calls():
    """setup_logging 可重复调用（工作台同进程跨域切换），随最近一次级别生效。"""
    setup_logging("DEBUG")
    setup_logging("INFO")

    assert logging.getLogger("httpx").level == logging.WARNING


@pytest.mark.usefixtures("_restore_logging")
def test_transport_info_noise_suppressed_but_warnings_pass(monkeypatch):
    """端到端：INFO 级下 httpx 传输噪声不落 stderr，WARNING 真故障仍可见。"""
    stream = io.StringIO()
    monkeypatch.setattr(sys, "stderr", stream)
    setup_logging("INFO")

    logging.getLogger("httpx").info("HTTP Request: POST https://llm.example.com %s", '"200 OK"')
    logging.getLogger("httpx").warning("Retrying request to /v1/messages")

    out = stream.getvalue()
    assert "HTTP Request" not in out
    assert "Retrying request" in out
