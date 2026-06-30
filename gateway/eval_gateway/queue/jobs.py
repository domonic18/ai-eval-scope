"""任务队列 — PG 持久化，worker 用 FOR UPDATE SKIP LOCKED 抢占。"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from eval_gateway.auth.deps import Tenant
from eval_gateway.core.logging import get_logger
from eval_gateway.core.types import JobStatus
from eval_gateway.models.db import Job

LOG = get_logger(__name__)


async def enqueue(
    session: AsyncSession,
    tenant: Tenant,
    *,
    job_id: str,
    input_kind: str,
    scope: str,
    input_ref: str,
    rule_set_id: str,
    task_id: str | None = None,
    task_title: str | None = None,
    task_subject: str | None = None,
) -> Job:
    """第三方提交的任务入队。"""
    job = Job(
        job_id=job_id,
        project_id=tenant.project_id,
        org_id=tenant.org_id,
        status=JobStatus.QUEUED.value,
        input_kind=input_kind,
        scope=scope,
        input_ref=input_ref,
        rule_set_id=rule_set_id,
        task_id=task_id,
        task_title=task_title,
        task_subject=task_subject,
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    LOG.info("job.enqueued", job_id=job_id, project_id=tenant.project_id)
    return job


async def claim(session: AsyncSession) -> Job | None:
    """原子抢占一个 queued 任务。"""
    stmt = text(
        """
        SELECT job_id FROM gateway.jobs
        WHERE status = 'queued'
        ORDER BY created_at ASC
        FOR UPDATE SKIP LOCKED
        LIMIT 1
        """
    )
    result = await session.execute(stmt)
    row = result.first()
    if row is None:
        return None

    job_id = row[0]
    job = await session.get(Job, job_id)
    if job is None:
        return None

    job.status = JobStatus.RUNNING.value
    job.started_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(job)
    LOG.info("job.claimed", job_id=job_id)
    return job


async def get_job(
    session: AsyncSession,
    job_id: str,
    tenant: Tenant | None = None,
) -> Job | None:
    """查询任务；若提供 tenant 则校验 project_id 归属。"""
    stmt = select(Job).where(Job.job_id == job_id)
    result = await session.execute(stmt)
    job = result.scalar_one_or_none()
    if job is None:
        return None
    if tenant is not None and job.project_id != tenant.project_id:
        return None
    return job


async def mark_done(
    session: AsyncSession,
    job_id: str,
    *,
    run_id: str,
    metrics: dict[str, Any],
    web_run_url: str | None,
) -> None:
    """评估成功完成。"""
    stmt = text(
        """
        UPDATE gateway.jobs
        SET status = 'completed',
            run_id = :run_id,
            metrics = CAST(:metrics AS jsonb),
            web_run_url = :web_run_url,
            finished_at = now()
        WHERE job_id = :job_id
        """
    )
    await session.execute(
        stmt,
        {
            "job_id": job_id,
            "run_id": run_id,
            "metrics": json.dumps(metrics, ensure_ascii=False),
            "web_run_url": web_run_url,
        },
    )
    await session.commit()
    LOG.info("job.completed", job_id=job_id, run_id=run_id)


async def mark_failed(
    session: AsyncSession,
    job_id: str,
    *,
    error: dict[str, Any],
) -> None:
    """评估失败。"""
    stmt = text(
        """
        UPDATE gateway.jobs
        SET status = 'failed',
            error = CAST(:error AS jsonb),
            finished_at = now()
        WHERE job_id = :job_id
        """
    )
    await session.execute(stmt, {"job_id": job_id, "error": json.dumps(error, ensure_ascii=False)})
    await session.commit()
    LOG.info("job.failed", job_id=job_id, error=error)


async def mark_cancelled(session: AsyncSession, job_id: str) -> bool:
    """尽力取消：仅 queued 状态可取消。"""
    stmt = text(
        """
        UPDATE gateway.jobs
        SET status = 'failed',
            error = '{"message": "cancelled by user"}'::jsonb,
            finished_at = now()
        WHERE job_id = :job_id AND status = 'queued'
        """
    )
    result = await session.execute(stmt, {"job_id": job_id})
    await session.commit()
    rowcount: int = getattr(result, "rowcount", 0) or 0
    return rowcount == 1
