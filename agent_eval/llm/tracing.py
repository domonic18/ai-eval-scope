"""Langfuse 追踪模块 — LLM 调用可观测性。

Cloud SaaS 模式：通过环境变量配置 LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY / LANGFUSE_HOST。
未配置时自动禁用，对评估流程无任何影响。

Langfuse v4 API:
  - 客户端: Langfuse(public_key, secret_key, host)
  - 创建 Trace: create_trace_id(seed=...) + TraceContext(trace_id=...)
  - 创建观察: start_observation(name, trace_context, as_type, ...)
  - 嵌套观察: parent.start_observation(name, as_type='generation', ...)
  - 更新结果: observation.update(output=..., usage_details=...)
  - 结束: observation.end()
"""

from __future__ import annotations

import os
from typing import Any, Optional

import structlog

logger = structlog.get_logger("tracing")

_langfuse_client: Optional[Langfuse] = None


def get_langfuse() -> Optional[Langfuse]:
    """获取 Langfuse 客户端单例。

    首次调用时从环境变量读取配置并初始化客户端。
    未配置 LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY 时返回 None。

    Returns:
        Langfuse 客户端实例，或 None（未配置时）。
    """
    global _langfuse_client
    if _langfuse_client is not None:
        return _langfuse_client

    public_key = os.environ.get("LANGFUSE_PUBLIC_KEY", "")
    secret_key = os.environ.get("LANGFUSE_SECRET_KEY", "")

    if not public_key or not secret_key:
        return None

    try:
        from langfuse import Langfuse

        host = os.environ.get("LANGFUSE_HOST", "https://cloud.langfuse.com")
        _langfuse_client = Langfuse(
            public_key=public_key,
            secret_key=secret_key,
            host=host,
        )
        logger.info("Langfuse 已启用", host=host)
        return _langfuse_client
    except Exception as e:
        logger.warning("Langfuse 初始化失败，追踪将不可用", error=str(e))
        return None


def create_trace(name: str, metadata: dict[str, Any] | None = None) -> Optional[tuple[Any, dict[str, str]]]:
    """创建 Langfuse Trace（根 Span）。

    Args:
        name: Trace 名称，如 "judge:logical_consistency"。
        metadata: Trace 元数据。

    Returns:
        (span, trace_context_dict) 元组，或 None（未启用时）。
    """
    langfuse = get_langfuse()
    if langfuse is None:
        return None

    trace_id = langfuse.create_trace_id(seed=name)
    # TraceContext 是 TypedDict，等价于 {"trace_id": str}
    trace_ctx: dict[str, str] = {"trace_id": trace_id}

    span = langfuse.start_observation(
        name=name,
        trace_context=trace_ctx,
        as_type="span",
        metadata=metadata or {},
    )
    return span, trace_ctx


def is_tracing_enabled() -> bool:
    """检查 Langfuse 追踪是否已启用。"""
    return get_langfuse() is not None


def flush_traces() -> None:
    """刷新所有待发送的 trace 数据。

    在评估结束时调用，确保 Langfuse SDK 异步缓冲区的数据全部发送到服务端。
    """
    if _langfuse_client is not None:
        _langfuse_client.flush()
        logger.debug("Langfuse trace 数据已刷新")


def reset_langfuse() -> None:
    """重置 Langfuse 客户端（仅用于测试）。"""
    global _langfuse_client
    _langfuse_client = None
