"""执行引擎默认参数配置测试。"""

from __future__ import annotations

from pathlib import Path

from agent_eval.config import AGENT_DEFAULTS, SUT_TOOLS_DEFAULTS, TASK_DEFAULTS


class TestSUTToolsDefaults:
    """SUT Tools 默认参数测试。"""

    def test_http_timeout(self) -> None:
        """HTTP SUT 默认超时。"""
        assert SUT_TOOLS_DEFAULTS.http_timeout == 120.0

    def test_cli_timeout(self) -> None:
        """CLI SUT 默认超时。"""
        assert SUT_TOOLS_DEFAULTS.cli_default_timeout == 120.0

    def test_file_patterns(self) -> None:
        """默认文件匹配模式。"""
        assert SUT_TOOLS_DEFAULTS.file_patterns == ["*.html", "*.htm"]


class TestAgentDefaults:
    """ExecutionAgent 默认参数测试。"""

    def test_max_turns(self) -> None:
        """单任务最大交互轮次。"""
        assert AGENT_DEFAULTS.max_turns == 20

    def test_max_budget_usd(self) -> None:
        """单任务最大预算。"""
        assert AGENT_DEFAULTS.max_budget_usd == 1.0

    def test_max_retries(self) -> None:
        """工具调用失败最大重试次数。"""
        assert AGENT_DEFAULTS.max_retries == 3

    def test_default_model(self) -> None:
        """默认使用模型。"""
        assert AGENT_DEFAULTS.model == "claude-sonnet-4-20250514"

    def test_workspace_dir(self) -> None:
        """默认工作空间目录。"""
        assert AGENT_DEFAULTS.workspace_dir == Path("./workspace")

    def test_permission_mode(self) -> None:
        """默认权限模式。"""
        assert AGENT_DEFAULTS.permission_mode == "accept_edits"

    def test_allowed_tools(self) -> None:
        """默认允许使用的工具列表。"""
        assert "invoke_http_sut" in AGENT_DEFAULTS.allowed_tools
        assert "invoke_cli_sut" in AGENT_DEFAULTS.allowed_tools
        assert "scan_directory" in AGENT_DEFAULTS.allowed_tools


class TestTaskDefaults:
    """Task 默认参数测试。"""

    def test_input_mode(self) -> None:
        """默认输入模式。"""
        assert TASK_DEFAULTS.input_mode == "inline"

    def test_file_patterns(self) -> None:
        """默认文件匹配模式。"""
        assert TASK_DEFAULTS.file_patterns == ["*.html"]
