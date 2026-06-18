"""SUT Tools (MCP) — SUT 交互工具集。

提供 invoke_http_sut、invoke_cli_sut、scan_directory、read_file、
collect_results、write_package、list_files 等 MCP Tool。
Sprint 8 实现，当前为骨架文件。
"""

from __future__ import annotations

from typing import Any


class SUTToolServer:
    """SUT 交互工具服务器，为 ExecutionAgent 提供 MCP Tools。

    将 HTTP 调用、CLI 执行、文件操作等能力包装为 MCP Tools，
    供 ExecutionAgent 根据任务描述自主调用。

    注意：本类将在 Sprint 8 中完整实现。当前仅提供接口骨架。
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}

    def get_tool_names(self) -> list[str]:
        """返回所有注册的工具名称。"""
        return [
            "invoke_http_sut",
            "invoke_cli_sut",
            "scan_directory",
            "read_file",
            "collect_results",
            "write_package",
            "list_files",
        ]

    def describe_tools(self) -> str:
        """返回工具描述，用于构建 System Prompt。"""
        tools = self.get_tool_names()
        return f"可用 SUT 工具: {', '.join(tools)}"
