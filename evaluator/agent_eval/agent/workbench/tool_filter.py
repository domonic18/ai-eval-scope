"""工作台 Agent 工具面复位（共享实现在 agent/core/tool_filter.py）。

域事实与设计动机（为何不能用 harness profile）见 core 模块注释；本模块仅
绑定工作台域的中间件名——deepagents _apply_custom_middleware 按名合并，
两域同进程运行时名称必须互异。
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from agent_eval.agent.core.tool_filter import filter_visible_tools


def build_toolset_filter(allowed_tools: Sequence[Any]) -> Any:
    """构造工作台域工具面复位中间件（中间件名 WorkbenchToolsetFilter）。"""
    from agent_eval.agent.core.tool_filter import build_toolset_filter as _build

    return _build(allowed_tools, middleware_name="WorkbenchToolsetFilter")


__all__ = ["build_toolset_filter", "filter_visible_tools"]
