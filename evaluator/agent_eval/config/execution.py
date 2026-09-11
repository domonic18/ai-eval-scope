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
    # LLM 角色（agent / vision / text；经 build_chat_model 桥接双协议——模型无关）
    llm_role: str = "agent"
    # 覆盖 provider 默认模型（None=用 provider 默认）
    model: str | None = None
    # 默认工作空间目录
    workspace_dir: Path = field(default_factory=lambda: Path("./workspace"))


@dataclass(frozen=True)
class InteractionPolicyDefaults:
    """交互预算（InteractionPolicy）默认参数（arch/16 §4.1 P1 声明式预算）。

    语义预算归 policy 声明，recursion_limit 由 derive_recursion_limit 自动推导为保险丝——
    不再以 max_turns 作为一等预算面。
    """

    # agent_run / agent_run_stream / run_on_thread 合计上限
    sut_calls_total: int = 8
    # 新会话首发（dispatch）至多 1 次
    dispatch: int = 1
    # 续跑 / 催促类（run_on_thread）
    nudges: int = 2
    # read_thread_state 取证
    state_polls: int = 60
    # download_sut_file
    downloads: int = 5
    # 两次催促最小间隔（秒）
    nudge_backoff_s: float = 30.0
    # 单任务墙钟（秒）
    wall_clock_deadline_s: float = 1500.0


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
INTERACTION_POLICY_DEFAULTS = InteractionPolicyDefaults()
TASK_DEFAULTS = TaskDefaults()
