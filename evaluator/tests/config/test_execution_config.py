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
        assert SUT_TOOLS_DEFAULTS.file_patterns == ["*"]  # 默认全收，由规则集 format 门控收敛


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
        """默认不锁定模型（None=用 provider 默认，v4.6 模型无关）。"""
        assert AGENT_DEFAULTS.model is None

    def test_llm_role(self) -> None:
        """默认 LLM 角色为 agent（经 build_chat_model 桥接双协议）。"""
        assert AGENT_DEFAULTS.llm_role == "agent"

    def test_workspace_dir(self) -> None:
        """默认工作空间目录。"""
        assert AGENT_DEFAULTS.workspace_dir == Path("./workspace")

    # v4.6 模型无关化移除 permission_mode / allowed_tools（工具与权限归
    # DeepAgents 底座管理，arch/03 §六）——对应测试同步清理


class TestTaskDefaults:
    """Task 默认参数测试。"""

    def test_input_mode(self) -> None:
        """默认输入模式。"""
        assert TASK_DEFAULTS.input_mode == "inline"

    def test_file_patterns(self) -> None:
        """默认文件匹配模式。"""
        assert TASK_DEFAULTS.file_patterns == ["*"]  # 默认全收，由规则集 format 门控收敛
