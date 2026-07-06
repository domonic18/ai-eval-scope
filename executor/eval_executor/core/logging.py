"""structlog 日志配置 -- 对齐 evaluator core/logging.py。"""

from __future__ import annotations

import logging
from typing import Any

import structlog


def setup_logging(level: str = "INFO", json_output: bool = False) -> None:
    """初始化 structlog：iso 时间戳，dev ConsoleRenderer 或 JSONRenderer。"""
    log_level = getattr(logging, level.upper(), logging.INFO)
    processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]
    renderer = (
        structlog.processors.JSONRenderer()
        if json_output
        else structlog.dev.ConsoleRenderer(colors=False)
    )
    structlog.configure(
        processors=processors + [renderer],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        cache_logger_on_first_use=False,
    )


def get_logger(name: str | None = None) -> Any:
    """获取一个 structlog logger。"""
    return structlog.get_logger(name)
