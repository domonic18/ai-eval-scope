"""执行侧数据模型。

定义任务（Task）、任务集（TaskSet）、SUT 响应（SUTResponse）、
执行轨迹（ExecutionTrace）、过程指标（ProcessMetrics）等执行引擎核心模型。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator

from agent_eval.config import AGENT_DEFAULTS, SUT_TOOLS_DEFAULTS, TASK_DEFAULTS


class Task(BaseModel):
    """单个评测任务 — 定义被测 Agent 需要完成的输入与期望。"""

    id: str = Field(description="任务唯一标识，如 math_grade7_001")
    # 场景包标识（Phase 0 新增，对齐 13 配置管理设计 §3.1）
    scenario_id: str | None = Field(
        default=None, description="所属场景 ID（命名空间），如 courseware"
    )
    package_id: str | None = Field(default=None, description="所属场景包 ID")
    input: dict[str, Any] = Field(
        description="输入参数（学科、年级、知识点等）",
    )
    expected: dict[str, Any] | None = Field(
        default=None,
        description="预期结果（知识点清单、约束等）",
    )
    constraints: dict[str, Any] = Field(
        default_factory=dict,
        description="约束条件（文档数量、格式等）",
    )
    # 目录模式字段
    input_mode: str = Field(
        default=TASK_DEFAULTS.input_mode,
        description='输入模式: "inline"（默认）或 "directory"（目录模式）',
    )
    directory_path: str | None = Field(
        default=None,
        description="目录路径（input_mode=directory 时必填）",
    )
    file_patterns: list[str] = Field(
        default_factory=lambda: list(TASK_DEFAULTS.file_patterns),
        description="文件匹配模式（如 [*.html, *.htm]）",
    )

    @field_validator("input_mode")
    @classmethod
    def validate_input_mode(cls, v: str) -> str:
        if v not in ("inline", "directory"):
            raise ValueError(f"input_mode 必须为 'inline' 或 'directory'，得到: {v!r}")
        return v

    model_config = {"extra": "allow"}


class TaskSet(BaseModel):
    """任务集 — 一组相关任务的集合。"""

    id: str = Field(description="任务集唯一标识")
    # 场景包标识（Phase 0 新增，对齐 13 配置管理设计 §3.1）
    # YAML 中以 `scenario:` 键承载场景 ID，Python 侧统一用 scenario_id
    scenario_id: str | None = Field(
        default=None,
        alias="scenario",
        description="所属场景 ID（命名空间），如 courseware",
    )
    package_id: str | None = Field(default=None, description="所属场景包 ID")
    name: str = Field(description="任务集名称")
    description: str = Field(default="", description="任务集描述")
    tasks: list[Task] = Field(default_factory=list, description="任务列表")

    model_config = {"extra": "allow", "populate_by_name": True}


class SUTResponse(BaseModel):
    """被测 Agent (SUT) 的响应。"""

    success: bool = Field(description="是否成功")
    output_files: list[str] = Field(
        default_factory=list,
        description="输出文件路径列表",
    )
    output_directory: str | None = Field(
        default=None,
        description="输出目录路径（目录模式时使用）",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Agent 返回的元数据",
    )
    error: str | None = Field(
        default=None,
        description="错误信息",
    )
    raw_response: dict[str, Any] = Field(
        default_factory=dict,
        description="原始响应数据",
    )


class ExecutionTrace(BaseModel):
    """执行轨迹 — 记录与 SUT 交互的完整过程。"""

    request: dict[str, Any] = Field(description="发送给 SUT 的请求")
    response: dict[str, Any] = Field(description="SUT 的响应")
    started_at: str = Field(description="开始时间（ISO 8601）")
    finished_at: str = Field(description="结束时间（ISO 8601）")
    error: str | None = Field(default=None, description="错误信息")


class ProcessMetrics(BaseModel):
    """过程指标 — 记录执行过程的量化数据。"""

    total_duration_ms: float = Field(default=0.0, description="总耗时（毫秒）")
    steps: int = Field(default=0, description="执行步骤数")
    retries: int = Field(default=0, description="重试次数")
    tool_calls: int = Field(default=0, description="工具调用次数")
    dead_end: bool = Field(default=False, description="是否进入死胡同")


class SUTToolsConfig(BaseModel):
    """SUT Tools 配置。"""

    # HTTP SUT 配置
    http_base_url: str | None = Field(default=None, description="默认 HTTP SUT 地址")
    http_default_headers: dict[str, str] = Field(
        default_factory=dict,
        description="默认请求头",
    )
    http_timeout: float = Field(
        default=SUT_TOOLS_DEFAULTS.http_timeout, description="默认超时（秒）"
    )

    # CLI SUT 配置
    cli_default_timeout: float = Field(
        default=SUT_TOOLS_DEFAULTS.cli_default_timeout, description="默认超时（秒）"
    )
    cli_working_dir: str | None = Field(default=None, description="默认工作目录")

    # 目录收集配置
    file_patterns: list[str] = Field(
        default_factory=lambda: list(SUT_TOOLS_DEFAULTS.file_patterns),
        description="默认文件匹配模式",
    )


class AgentConfig(BaseModel):
    """ExecutionAgent 配置 — 控制 Agent 执行行为（arch/03 §六 v4.6：模型无关）。"""

    # Agent 执行参数
    max_turns: int = Field(
        default=AGENT_DEFAULTS.max_turns,
        gt=0,
        description="单任务最大交互轮次",
    )
    max_budget_usd: float = Field(
        default=AGENT_DEFAULTS.max_budget_usd,
        ge=0.0,
        description="单任务最大预算（美元）",
    )
    max_retries: int = Field(
        default=AGENT_DEFAULTS.max_retries,
        ge=0,
        description="工具调用失败最大重试次数",
    )

    # 模型配置（v4.6 双协议桥接；LLM② 起走角色注册表，见 arch/06 §4.6）
    llm_role: str = Field(
        default=AGENT_DEFAULTS.llm_role,
        description="执行侧 LLM 角色（text|vision|agent），经 build_chat_model 桥接",
    )
    model: str | None = Field(
        default=AGENT_DEFAULTS.model,
        description="覆盖 provider 默认模型（可选；None=用 provider 默认）",
    )

    # SUT 工具配置
    sut_tools_config: SUTToolsConfig | None = Field(
        default=None,
        description="SUT Tools 配置",
    )

    # 工作空间
    workspace_dir: Path = Field(
        default=AGENT_DEFAULTS.workspace_dir,
        description="执行包输出目录",
    )
