"""core/logging 的单元测试。"""

from __future__ import annotations

import io
import sys

from agent_eval.core.logging import _ensure_utf8_streams


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
