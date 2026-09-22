"""WorkbenchToolsetFilter 单测 — 模型可见工具面复位。

纯函数部分全离线直测；中间件部分 pytest.importorskip（langchain 属 [agent]
extra，未装环境自动跳过——模块顶层不依赖 langchain，收集期不炸）。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from agent_eval.agent.workbench.tool_filter import (
    build_toolset_filter,
    filter_visible_tools,
)


def _tool(name: str) -> SimpleNamespace:
    return SimpleNamespace(name=name)


class TestFilterVisibleTools:
    """身份过滤纯函数——同名内置工具必须按身份（而非按名）剥除。"""

    def test_keeps_only_allowed_identities(self) -> None:
        sandbox_read = _tool("read_file")  # 自家沙盒工具（允许）
        injected_read = _tool("read_file")  # deepagents 内置同名工具（须剥除）
        allowed = [sandbox_read, _tool("write_file")]
        result = filter_visible_tools([sandbox_read, injected_read, _tool("task")], allowed)
        assert result == [sandbox_read]

    def test_all_unmatched_falls_back_noop(self) -> None:
        """全部失配 = 上游契约漂移（框架拷贝了工具对象）→ 原样返回，不交白卷。"""
        tools = [_tool("ls"), _tool("glob")]
        assert filter_visible_tools(tools, [_tool("read_file")]) == tools

    def test_empty_allowed_returns_original(self) -> None:
        tools = [_tool("ls")]
        assert filter_visible_tools(tools, []) == tools

    def test_none_request_tools_returns_empty(self) -> None:
        assert filter_visible_tools(None, [_tool("x")]) == []


class TestBuildToolsetFilter:
    """中间件工厂——wrap_model_call 内 request.override(tools=过滤结果)。"""

    def test_middleware_name_unique(self) -> None:
        pytest.importorskip("langchain.agents")
        mw = build_toolset_filter([_tool("read_file")])
        assert mw.name == "WorkbenchToolsetFilter"

    def test_wrap_model_call_overrides_tools(self) -> None:
        pytest.importorskip("langchain.agents")
        sandbox_read = _tool("read_file")
        mw = build_toolset_filter([sandbox_read])
        seen: list[list[SimpleNamespace]] = []

        class _Request(SimpleNamespace):
            def override(self, *, tools: list[SimpleNamespace]) -> SimpleNamespace:
                seen.append(tools)
                return SimpleNamespace(tools=tools, overridden=True)

        request = _Request(tools=[sandbox_read, _tool("task"), _tool("ls")])

        def passthrough(req: SimpleNamespace) -> SimpleNamespace:
            return req

        result = mw.wrap_model_call(request, passthrough)
        assert result.overridden is True
        assert seen[0] == [sandbox_read]

    def test_awrap_model_call_overrides_tools(self) -> None:
        import asyncio

        pytest.importorskip("langchain.agents")
        sandbox_read = _tool("read_file")
        mw = build_toolset_filter([sandbox_read])
        seen: list[list[SimpleNamespace]] = []

        class _Request(SimpleNamespace):
            def override(self, *, tools: list[SimpleNamespace]) -> SimpleNamespace:
                seen.append(tools)
                return SimpleNamespace(tools=tools, overridden=True)

        async def passthrough(req: SimpleNamespace) -> SimpleNamespace:
            return req

        result = asyncio.run(
            mw.awrap_model_call(_Request(tools=[sandbox_read, _tool("task")]), passthrough)
        )
        assert result.overridden is True and seen[0] == [sandbox_read]

    def test_noop_fallback_preserves_tools(self) -> None:
        """身份全失配时中间件不得清空工具面（保守降级语义贯通到 override）。"""
        pytest.importorskip("langchain.agents")
        mw = build_toolset_filter([_tool("unrelated")])
        tools = [_tool("ls"), _tool("glob")]

        class _Request(SimpleNamespace):
            def override(self, *, tools: list[SimpleNamespace]) -> SimpleNamespace:
                return SimpleNamespace(tools=tools, overridden=True)

        result = mw.wrap_model_call(_Request(tools=tools), lambda req: req)
        assert result.tools == tools
