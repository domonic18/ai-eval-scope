"""执行引擎默认参数配置。

集中管理 ExecutionAgent、SUT Tools、Task 等执行侧模型的默认值，避免散落在
execution/models.py 等模块中 hardcode。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class SUTToolsDefaults:
    """SUT Tools 默认参数。"""

    # HTTP SUT 默认超时（秒）
    http_timeout: float = 120.0
    # CLI SUT 默认超时（秒）
    cli_default_timeout: float = 120.0
    # 默认文件匹配模式（目录收集时使用）
    file_patterns: list[str] = field(default_factory=lambda: ["*.html", "*.htm"])


@dataclass(frozen=True)
class AgentDefaults:
    """ExecutionAgent 默认参数。"""

    # 单任务最大交互轮次
    max_turns: int = 20
    # 单任务最大预算（美元）
    max_budget_usd: float = 1.0
    # 工具调用失败最大重试次数
    max_retries: int = 3
    # 默认使用模型
    model: str = "claude-sonnet-4-20250514"
    # 默认工作空间目录
    workspace_dir: Path = field(default_factory=lambda: Path("./workspace"))
    # Agent 权限模式
    permission_mode: str = "accept_edits"
    # 默认允许使用的工具列表
    allowed_tools: list[str] = field(
        default_factory=lambda: [
            "invoke_http_sut",
            "invoke_cli_sut",
            "scan_directory",
            "read_file",
            "collect_results",
            "write_package",
            "list_files",
        ]
    )


@dataclass(frozen=True)
class TaskDefaults:
    """Task 默认参数。"""

    # 默认输入模式
    input_mode: str = "inline"
    # 默认文件匹配模式
    file_patterns: list[str] = field(default_factory=lambda: ["*.html"])


# 模块级单例
SUT_TOOLS_DEFAULTS = SUTToolsDefaults()
AGENT_DEFAULTS = AgentDefaults()
TASK_DEFAULTS = TaskDefaults()
