"""Pydantic 请求/响应模型。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from eval_gateway.core.types import InputKind, JobStatus, Scope


class ContentInline(BaseModel):
    """内联内容字段。"""

    filename: str = Field(description="文件名（如 lesson-01.md）")
    text: str = Field(description="文件内容")


class JobCreateInline(BaseModel):
    """内联 JSON 提交请求体。"""

    content: ContentInline = Field(description="内联的单个文件内容")
    task_id: str | None = Field(default=None, description="任务标识（决定 run 内 sample_id）")
    task_title: str | None = Field(default=None, description="任务标题")
    task_subject: str | None = Field(default=None, description="学科")
    rule_set_id: str = Field(default="coursework-quality", description="规则集标识")


class JobResponse(BaseModel):
    """任务状态响应。"""

    job_id: str
    status: JobStatus
    project_id: str
    org_id: str
    input_kind: InputKind
    scope: Scope
    rule_set_id: str
    task_id: str | None = None
    task_title: str | None = None
    task_subject: str | None = None
    run_id: str | None
    web_run_url: str | None
    metrics: dict[str, Any] | None
    # 透明度：HTTP 调用方看不到进程日志，须显式暴露实际跑了什么
    capabilities: dict[str, Any] | None = None  # {"required":[...], "provisioned":[...]}
    skipped: list[dict[str, Any]] | None = None  # [{"evaluator":..., "reason":...}]
    error: dict[str, Any] | None
    created_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None


class JobSubmissionResponse(BaseModel):
    """提交任务后的 202 响应。"""

    job_id: str
    status: JobStatus
    # 归属信息（由 API Key 验签解析，调用方无需也无需在请求体传 project_id）
    project_id: str
    org_id: str
    web_run_url: str | None
    poll_url: str


class ErrorResponse(BaseModel):
    """统一错误响应。"""

    error: str
    code: str
    details: dict[str, Any] | None = None
