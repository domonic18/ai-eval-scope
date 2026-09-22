"""structlog 日志初始化。"""

from __future__ import annotations

import io
import logging
import sys
from typing import Any

import structlog
from structlog.typing import Processor

from agent_eval.core.exec_events import EXEC_EVENT_LOGGER


def _ensure_utf8_streams() -> None:
    """强制 stdout/stderr 为 UTF-8，规避非 UTF-8 locale 下输出中文日志时的编码错误。"""
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8", errors="replace")


# 传输层噪声日志器：httpx / openai / anthropic SDK 每次请求都打 INFO 级
# 「HTTP Request: … 200 OK」「Retrying request …」，在交互式会话（工作台流式直播）
# 是纯污染——root 日志是进程级全局态，工作台里执行域先跑过一次评测，日志就会混进
# 之后所有 Agent 会话。非 DEBUG 模式压到 WARNING（真故障仍可见）；DEBUG（--log-level
# debug 诊断）不压，全量放行。
_NOISY_HTTP_LOGGERS = ("httpx", "httpcore", "openai", "anthropic")

# 执行日志四档：quiet=仅结果行 / normal=现状默认 / verbose=过程事件
# 直出（SUT 请求响应摘要、judge 交互、重试，见 core/exec_events.py）/ debug=全量原文。
_LOG_LEVEL_MAP = {
    "quiet": "WARNING",
    "normal": "INFO",
    "verbose": "INFO",
    "debug": "DEBUG",
}


def resolve_logging_level(log_level: str) -> str:
    """执行日志档位（quiet/normal/verbose/debug）→ 根日志器级别名。

    Args:
        log_level: 档位名（大小写不敏感）。

    Raises:
        ValueError: 未知档位（CLI 层经 typer Enum 前置拦截，此处兜底）。
    """
    name = log_level.strip().lower()
    if name not in _LOG_LEVEL_MAP:
        raise ValueError(f"未知日志档位: {log_level!r}（合法值: {'|'.join(_LOG_LEVEL_MAP)}）")
    return _LOG_LEVEL_MAP[name]


def _tune_noisy_loggers(level: str) -> None:
    """按根级别收敛传输层日志器级别（setup_logging 可重复调用，随最近一次生效）。"""
    noisy_level = logging.NOTSET if level.upper() == "DEBUG" else logging.WARNING
    for name in _NOISY_HTTP_LOGGERS:
        logging.getLogger(name).setLevel(noisy_level)


class _DemoteSubWarningTracebacks(logging.Filter):
    """WARNING 以下记录摘除 exc_info——堆栈面板只属于真告警。

    第三方库惯于在 DEBUG 级挂良性堆栈（实测 deepagents 对「可选 prompt-caching
    中间件缺失」每条 debug 记录附带 ModuleNotFoundError 的 exc_info），rich 渲染
    后每条都是整屏 locals 面板，一次执行四五块，真故障的信噪比反被淹没。摘除
    exc_info 只留消息行；WARNING 及以上堆栈完整渲染，诊断能力不受损。
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if record.levelno < logging.WARNING and record.exc_info:
            record.exc_info = None
            record.exc_text = None  # 防御：曾被其他 handler 格式化过的残留
        return True


def setup_logging(level: str = "INFO", json_output: bool = False) -> None:
    """初始化 structlog 配置。

    Args:
        level: 日志级别（DEBUG/INFO/WARNING/ERROR；四档经 ``resolve_logging_level``
            归一后传入）。
        json_output: 是否输出 JSON 格式（默认为控制台友好的 dev 格式）。

    非 DEBUG 级别下同步把传输层日志器（httpx/httpcore/openai/anthropic）压到
    WARNING——交互式会话不被「HTTP Request: …」INFO 噪声污染；DEBUG 诊断模式
    全量放行（见 ``_NOISY_HTTP_LOGGERS``）。
    """
    _ensure_utf8_streams()
    _tune_noisy_loggers(level)
    _isolate_exec_event_logger()

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
    handler.addFilter(_DemoteSubWarningTracebacks())
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


class _ExecEventLineHandler(logging.Handler):
    """verbose/debug 档执行事件行渲染器：``· <事件消息>`` 直出 stderr。

    纯文本行（非 rich）——verbose 档的重要场景是 CI 与长评测人读过程，
    确定性平文比终端样式更可靠。
    """

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            sys.stderr.write(f"· {msg}\n")
        except Exception:  # noqa: BLE001 — 日志渲染失败绝不反噬执行主流程
            self.handleError(record)


def _isolate_exec_event_logger() -> None:
    """隔离执行事件日志器：propagate=False，normal/quiet 档静默丢弃。

    事件走独立日志器（``agent_eval.exec``）而非 root——若走 root，normal 档
    （INFO）会把每条事件以 dev 格式打到 stderr，档位语义（过程事件仅 verbose
    可见）即失效。隔离后事件只在 ``install_exec_event_handler`` 挂上渲染器时
    才可见，且永不与 root 的 dev 格式重复。
    """
    event_logger = logging.getLogger(EXEC_EVENT_LOGGER)
    event_logger.propagate = False
    event_logger.setLevel(logging.INFO)
    event_logger.handlers.clear()


def install_exec_event_handler(*, enabled: bool) -> None:
    """按档位挂/摘执行事件行渲染器（verbose/debug 挂载，幂等可重复调用）。

    setup_logging 每次调用都会重置事件日志器（清 handler），故本函数须在
    setup_logging 之后调用；重复调用先摘后挂，不累积。
    """
    _isolate_exec_event_logger()
    if not enabled:
        return
    handler = _ExecEventLineHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    logging.getLogger(EXEC_EVENT_LOGGER).addHandler(handler)
