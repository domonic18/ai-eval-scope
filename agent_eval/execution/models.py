"""执行侧数据模型。

定义任务（Task）、任务集（TaskSet）、SUT 响应（SUTResponse）、
执行轨迹（ExecutionTrace）、过程指标（ProcessMetrics）等执行引擎核心模型。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator


class Task(BaseModel):
    """单个评测任务 — 定义被测 Agent 需要完成的输入与期望。"""

    id: str = Field(description="任务唯一标识，如 math_grade7_001")
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
        default="inline",
        description='输入模式: "inline"（默认）或 "directory"（目录模式）',
    )
    directory_path: str | None = Field(
        default=None,
        description="目录路径（input_mode=directory 时必填）",
    )
    file_patterns: list[str] = Field(
        default_factory=lambda: ["*.html"],
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
    name: str = Field(description="任务集名称")
    description: str = Field(default="", description="任务集描述")
    tasks: list[Task] = Field(default_factory=list, description="任务列表")

    model_config = {"extra": "allow"}


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
        default_factory=dict, description="默认请求头",
    )
    http_timeout: float = Field(default=120.0, description="默认超时（秒）")

    # CLI SUT 配置
    cli_default_timeout: float = Field(default=120.0, description="默认超时（秒）")
    cli_working_dir: str | None = Field(default=None, description="默认工作目录")

    # 目录收集配置
    file_patterns: list[str] = Field(
        default_factory=lambda: ["*.html", "*.htm"],
        description="默认文件匹配模式",
    )


class AgentConfig(BaseModel):
    """ExecutionAgent 配置 — 控制 Agent 执行行为。"""

    # Agent 执行参数
    max_turns: int = Field(
        default=20,
        gt=0,
        description="单任务最大交互轮次",
    )
    max_budget_usd: float = Field(
        default=1.0,
        ge=0.0,
        description="单任务最大预算（美元）",
    )
    max_retries: int = Field(
        default=3,
        ge=0,
        description="工具调用失败最大重试次数",
    )

    # 模型配置
    model: str = Field(
        default="claude-sonnet-4-20250514",
        description="Agent 使用的模型",
    )

    # SUT 工具配置
    sut_tools_config: SUTToolsConfig | None = Field(
        default=None,
        description="SUT Tools 配置",
    )

    # 工作空间
    workspace_dir: Path = Field(
        default=Path("./workspace"),
        description="执行包输出目录",
    )

    # 权限模式
    permission_mode: str = Field(
        default="accept_edits",
        description="Agent 权限模式",
    )

    # 允许的工具列表
    allowed_tools: list[str] = Field(
        default_factory=lambda: [
            "invoke_http_sut",
            "invoke_cli_sut",
            "scan_directory",
            "read_file",
            "collect_results",
            "write_package",
            "list_files",
        ],
        description="Agent 允许使用的工具列表",
    )
