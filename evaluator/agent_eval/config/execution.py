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
    # 默认文件匹配模式（目录收集时使用）；默认全收 ["*"]，由规则集 format 门控/调用方收敛
    file_patterns: list[str] = field(default_factory=lambda: ["*"])


@dataclass(frozen=True)
class AgentDefaults:
    """ExecutionAgent 默认参数（arch/03 §六 v4.6：模型无关）。"""

    # 单任务最大交互轮次
    max_turns: int = 20
    # 单任务最大预算（美元）
    max_budget_usd: float = 1.0
    # 工具调用失败最大重试次数
    max_retries: int = 3
    # llm_config.yaml 中的 provider 名（经 build_chat_model 桥接双协议——模型无关）
    llm_role: str = "agent"
    # 覆盖 provider 默认模型（None=用 provider 默认）
    model: str | None = None
    # 默认工作空间目录
    workspace_dir: Path = field(default_factory=lambda: Path("./workspace"))


@dataclass(frozen=True)
class TaskDefaults:
    """Task 默认参数。"""

    # 默认输入模式
    input_mode: str = "inline"
    # 默认文件匹配模式；默认全收 ["*"]，由规则集 format 门控/调用方收敛（去 courseware html 偏向）
    file_patterns: list[str] = field(default_factory=lambda: ["*"])


# 模块级单例
SUT_TOOLS_DEFAULTS = SUTToolsDefaults()
AGENT_DEFAULTS = AgentDefaults()
TASK_DEFAULTS = TaskDefaults()
