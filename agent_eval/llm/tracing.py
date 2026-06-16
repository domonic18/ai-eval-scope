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
import uuid
from typing import Any

import structlog

from agent_eval.llm.config import LANGFUSE_DEFAULTS

logger = structlog.get_logger("tracing")

_langfuse_client: Any | None = None


def get_langfuse() -> Any | None:
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

        host = os.environ.get("LANGFUSE_HOST", LANGFUSE_DEFAULTS.host)
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


def create_trace(
    name: str, metadata: dict[str, Any] | None = None
) -> tuple[Any, dict[str, str]] | None:
    """创建 Langfuse Trace（根 Span）。

    每次调用生成全局唯一的 trace_id（UUID），确保不同评测任务/运行不会共享同一个
    Langfuse trace。

    Args:
        name: Trace 显示名称，如 "eval:run_xxx" 或 "judge:logical_consistency"。
        metadata: Trace 元数据。

    Returns:
        (span, trace_context_dict) 元组，或 None（未启用时）。
    """
    langfuse = get_langfuse()
    if langfuse is None:
        return None

    # 使用 UUID 生成唯一 trace_id，避免不同运行/任务因同名而共享 trace
    trace_id = uuid.uuid4().hex
    trace_ctx: dict[str, str] = {"trace_id": trace_id}

    span = langfuse.start_observation(
        name=name,
        trace_context=trace_ctx,
        as_type="span",
        metadata=metadata or {},
    )
    return span, trace_ctx


def create_span(
    name: str,
    trace_id: str,
    metadata: dict[str, Any] | None = None,
) -> Any | None:
    """在已有 Trace 下创建子 Span。

    用于把多个相关观察（如一次评测运行中的多次 LLM Judge）归到同一个 trace 下。

    Args:
        name: Span 名称。
        trace_id: 父 Trace ID。
        metadata: Span 元数据。

    Returns:
        Span 对象，或 None（未启用时）。
    """
    langfuse = get_langfuse()
    if langfuse is None:
        return None

    return langfuse.start_observation(
        name=name,
        trace_context={"trace_id": trace_id},
        as_type="span",
        metadata=metadata or {},
    )


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
