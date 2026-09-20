"""core/logging 的单元测试。"""

from __future__ import annotations

import io
import logging
import sys

import pytest

from agent_eval.core.exec_events import EXEC_EVENT_LOGGER
from agent_eval.core.logging import (
    _NOISY_HTTP_LOGGERS,
    _ensure_utf8_streams,
    install_exec_event_handler,
    resolve_logging_level,
    setup_logging,
)


@pytest.fixture
def _restore_logging():
    """保存并恢复 root 与传输层日志器的全局态（setup_logging 是进程级副作用）。"""
    root = logging.getLogger()
    saved = (root.handlers[:], root.level)
    saved_noisy = {n: logging.getLogger(n).level for n in _NOISY_HTTP_LOGGERS}
    event_logger = logging.getLogger(EXEC_EVENT_LOGGER)
    saved_event = (event_logger.handlers[:], event_logger.level, event_logger.propagate)
    yield
    root.handlers[:] = saved[0]
    root.setLevel(saved[1])
    for name, level in saved_noisy.items():
        logging.getLogger(name).setLevel(level)
    event_logger.handlers[:] = saved_event[0]
    event_logger.setLevel(saved_event[1])
    event_logger.propagate = saved_event[2]


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
    """DEBUG（--log-level debug 诊断）：传输层日志器回 NOTSET 随根级别，全量放行。"""
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


# ── 执行日志四档（arch/15 §4.4，Sprint 14a）─────────────────────────────────


@pytest.mark.parametrize(
    ("quad", "expected"),
    [
        ("quiet", "WARNING"),
        ("normal", "INFO"),
        ("verbose", "INFO"),
        ("debug", "DEBUG"),
        ("QUIET", "WARNING"),  # 大小写不敏感
    ],
)
def test_resolve_logging_level_maps_quad(quad: str, expected: str) -> None:
    """四档 → 根日志器级别映射。"""
    assert resolve_logging_level(quad) == expected


def test_resolve_logging_level_rejects_unknown() -> None:
    """未知档位显式报错（CLI 层由 typer 前置拦截，此处兜底）。"""
    with pytest.raises(ValueError, match="未知日志档位"):
        resolve_logging_level("loud")


@pytest.mark.usefixtures("_restore_logging")
def test_exec_event_logger_isolated_from_root() -> None:
    """事件日志器 propagate=False：事件绝不以 dev 格式漏进 root（normal 档静默）。"""
    setup_logging("INFO")

    event_logger = logging.getLogger(EXEC_EVENT_LOGGER)
    assert event_logger.propagate is False
    assert event_logger.handlers == []


@pytest.mark.usefixtures("_restore_logging")
def test_exec_events_silent_at_normal(monkeypatch):
    """normal 档：事件发射不落 stderr（档位语义——过程事件仅 verbose 可见）。"""
    from agent_eval.core import exec_events

    stream = io.StringIO()
    monkeypatch.setattr(sys, "stderr", stream)
    setup_logging("INFO")

    exec_events.sut_request(method="POST", url="https://sut.example.com/api", status=200)

    assert stream.getvalue() == ""


@pytest.mark.usefixtures("_restore_logging")
def test_exec_events_rendered_when_handler_installed(monkeypatch):
    """verbose 档（挂渲染器）：事件以「· 消息」平文行直出 stderr。"""
    from agent_eval.core import exec_events

    stream = io.StringIO()
    monkeypatch.setattr(sys, "stderr", stream)
    setup_logging("INFO")
    install_exec_event_handler(enabled=True)

    exec_events.sut_request(method="POST", url="https://sut.example.com/api", status=200)

    out = stream.getvalue()
    assert "· SUT POST https://sut.example.com/api → 200" in out


@pytest.mark.usefixtures("_restore_logging")
def test_install_exec_event_handler_disabled_removes_previous(monkeypatch):
    """enabled=False 幂等摘除：先 verbose 后 normal 切换不残留渲染器（工作台跨域复用）。"""
    stream = io.StringIO()
    monkeypatch.setattr(sys, "stderr", stream)
    setup_logging("INFO")

    install_exec_event_handler(enabled=True)
    install_exec_event_handler(enabled=False)

    logging.getLogger(EXEC_EVENT_LOGGER).info("残留事件")
    assert stream.getvalue() == ""


# ── 子告警堆栈降噪（debug 档第三方良性 exc_info 不渲染整屏面板）──────────────


@pytest.mark.usefixtures("_restore_logging")
def test_subwarning_exc_info_renders_message_without_traceback(monkeypatch):
    """WARNING 以下记录挂 exc_info 只留消息行（deepagents「可选依赖缺失」良性堆栈降噪）。"""
    stream = io.StringIO()
    monkeypatch.setattr(sys, "stderr", stream)
    setup_logging("DEBUG")

    try:
        raise ModuleNotFoundError("No module named 'langchain_aws'")
    except ModuleNotFoundError as exc:
        logging.getLogger("deepagents.middleware._prompt_caching").debug(
            "Bedrock prompt caching middleware is unavailable.", exc_info=exc
        )

    out = stream.getvalue()
    assert "Bedrock prompt caching middleware is unavailable." in out  # 消息行保留
    assert "Traceback" not in out  # 堆栈面板不渲染


@pytest.mark.usefixtures("_restore_logging")
def test_warning_exc_info_still_renders_traceback(monkeypatch):
    """WARNING 及以上堆栈完整渲染——降噪不损失真故障诊断能力。"""
    stream = io.StringIO()
    monkeypatch.setattr(sys, "stderr", stream)
    setup_logging("INFO")

    try:
        raise RuntimeError("SUT 连接失败")
    except RuntimeError as exc:
        logging.getLogger("agent_eval.test").warning("执行失败", exc_info=exc)

    out = stream.getvalue()
    assert "执行失败" in out
    assert "Traceback" in out
    assert "RuntimeError" in out
