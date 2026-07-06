"""任务队列 -- public.eval_jobs 持久化状态机。

- SCF 模式：Web 写 queued + Invoke → executor 读 job → mark_running → 执行 → mark_done/failed。
- worker 模式（本地）：executor 轮询 claim queued 任务。

提交（enqueue）与取消（cancel）由 Web 负责（Prisma），executor 不实现。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from eval_executor.core.logging import get_logger
from eval_executor.models.db import EvalJob

LOG = get_logger(__name__)


async def claim(session: AsyncSession) -> EvalJob | None:
    """原子抢占一个 queued 任务（worker 模式，FOR UPDATE SKIP LOCKED）。"""
    stmt = text(
        """
        SELECT job_id FROM eval_jobs
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
    job = await session.get(EvalJob, job_id)
    if job is None:
        return None

    job.status = "running"
    job.started_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(job)
    LOG.info("job.claimed", job_id=job_id)
    return job


async def mark_running(session: AsyncSession, job_id: str) -> bool:
    """置 running（SCF 模式 entrypoint 第一时间调用，缩小卡死窗口）。

    仅 queued 态可置 running；返回是否实际更新。
    """
    stmt = text(
        """
        UPDATE eval_jobs
        SET status = 'running', started_at = now()
        WHERE job_id = :job_id AND status = 'queued'
        """
    )
    result = await session.execute(stmt, {"job_id": job_id})
    await session.commit()
    rowcount: int = getattr(result, "rowcount", 0) or 0
    return rowcount == 1


async def get_job(session: AsyncSession, job_id: str) -> EvalJob | None:
    """查询任务。"""
    stmt = select(EvalJob).where(EvalJob.job_id == job_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


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
        UPDATE eval_jobs
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
        UPDATE eval_jobs
        SET status = 'failed',
            error = CAST(:error AS jsonb),
            finished_at = now()
        WHERE job_id = :job_id
        """
    )
    await session.execute(stmt, {"job_id": job_id, "error": json.dumps(error, ensure_ascii=False)})
    await session.commit()
    LOG.info("job.failed", job_id=job_id)
