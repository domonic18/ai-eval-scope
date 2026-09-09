"""structlog 日志初始化。"""

from __future__ import annotations

import io
import logging
import sys
from typing import Any

import structlog
from structlog.typing import Processor


def _ensure_utf8_streams() -> None:
    """强制 stdout/stderr 为 UTF-8，规避非 UTF-8 locale 下输出中文日志时的编码错误。"""
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8", errors="replace")


# 传输层噪声日志器：httpx / openai / anthropic SDK 每次请求都打 INFO 级
# 「HTTP Request: … 200 OK」「Retrying request …」，在交互式会话（工作台流式直播）
# 是纯污染——root 日志是进程级全局态，工作台里执行域先跑过一次评测，日志就会混进
# 之后所有 Agent 会话。非 DEBUG 模式压到 WARNING（真故障仍可见）；DEBUG（--verbose
# 诊断）不压，全量放行。
_NOISY_HTTP_LOGGERS = ("httpx", "httpcore", "openai", "anthropic")


def _tune_noisy_loggers(level: str) -> None:
    """按根级别收敛传输层日志器级别（setup_logging 可重复调用，随最近一次生效）。"""
    noisy_level = logging.NOTSET if level.upper() == "DEBUG" else logging.WARNING
    for name in _NOISY_HTTP_LOGGERS:
        logging.getLogger(name).setLevel(noisy_level)


def setup_logging(level: str = "INFO", json_output: bool = False) -> None:
    """初始化 structlog 配置。

    Args:
        level: 日志级别（DEBUG/INFO/WARNING/ERROR）。
        json_output: 是否输出 JSON 格式（默认为控制台友好的 dev 格式）。

    非 DEBUG 级别下同步把传输层日志器（httpx/httpcore/openai/anthropic）压到
    WARNING——交互式会话不被「HTTP Request: …」INFO 噪声污染；DEBUG 诊断模式
    全量放行（见 ``_NOISY_HTTP_LOGGERS``）。
    """
    _ensure_utf8_streams()
    _tune_noisy_loggers(level)

    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]

    renderer: Processor
    if json_output:
        # JSON Lines 输出（适合生产环境 / 日志收集）
        renderer = structlog.processors.JSONRenderer()
    else:
        # 开发友好的控制台输出
        renderer = structlog.dev.ConsoleRenderer()

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # 配置标准库 logging
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            processor=renderer,
            foreign_pre_chain=shared_processors,
        )
    )
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(getattr(logging, level.upper(), logging.INFO))


def get_logger(name: str | None = None) -> Any:
    """获取 structlog 日志实例。

    Args:
        name: 日志器名称（通常为模块名）。

    Returns:
        structlog.BoundLogger 实例。
    """
    return structlog.get_logger(name)
