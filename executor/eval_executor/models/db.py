"""SQLAlchemy ORM 模型 -- public.eval_jobs 表（与 web Prisma 共享，由 make db-init 创建）。

executor 只读写本表 + 只读 public.api_keys（解密提交者 token 回传）；不在代码里建库。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """public schema 的 ORM 基类。"""


class EvalJob(Base):
    """评估任务 -- 由 Web 提交，executor 消费执行。"""

    __tablename__ = "eval_jobs"
    # public schema（默认，不设 __table_args__ schema）

    job_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    # 提交者 API Key id（回传时按此查第三方 token，让结果落到第三方项目）
    api_key_id: Mapped[str] = mapped_column(String(64), nullable=False)
    project_id: Mapped[str] = mapped_column(String(64), nullable=False)
    org_id: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="queued")
    input_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    scope: Mapped[str] = mapped_column(String(16), nullable=False)
    # 对象存储 key（输入）；executor 经 input_presigned_url 下载，不持对象存储凭据
    input_object_key: Mapped[str] = mapped_column(Text, nullable=False)
    input_presigned_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    rule_set_id: Mapped[str] = mapped_column(
        String(64), nullable=False, default="coursework-quality"
    )
    # 场景包引用 scenario/package:label（S2-D）；缺失视为历史 job，executor 拒绝执行。
    package_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # 调用方可设的任务标识/标题/学科（不填则由 builder 回退：单页→"contents"）
    task_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    task_title: Mapped[str | None] = mapped_column(String(256), nullable=True)
    task_subject: Mapped[str | None] = mapped_column(String(128), nullable=True)
    run_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    web_run_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    scf_request_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    metrics: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
