"""Worker 主循环 -- 本地 worker 模式（无 SCF event 时轮询 eval_jobs，本地开发用）。

生产模式由 SCF 事件函数触发（每次 Invoke 执行一个 job），不走此循环。
"""

from __future__ import annotations

import asyncio
from typing import Any

from eval_executor.config.settings import get_settings
from eval_executor.core.logging import get_logger
from eval_executor.executor.runner import run_job
from eval_executor.queue.jobs import claim, mark_failed
from eval_executor.storage.input_loader import load_input
from eval_executor.storage.session import make_sessionmaker

LOG = get_logger(__name__)


class WorkerLoop:
    """本地 worker 模式：轮询 queued 任务，并发执行。"""

    def __init__(self, concurrency: int = 2) -> None:
        self.concurrency = concurrency
        self._sem = asyncio.Semaphore(concurrency)
        self._running = False

    async def run(self) -> None:
        """阻塞运行 worker 循环（entrypoint worker 模式入口）。"""
        self._running = True
        LOG.info("worker.started", concurrency=self.concurrency)
        settings = get_settings()
        while self._running:
            try:
                async with make_sessionmaker()() as session:
                    job = await claim(session)
                if job is None:
                    await asyncio.sleep(settings.poll_interval_sec)
                    continue

                async with self._sem:
                    LOG.info("worker.running", job_id=job.job_id)
                    await self._run_one(job)
            except asyncio.CancelledError:
                break
            except Exception as exc:  # noqa: BLE001
                LOG.exception("worker.loop.error", error=str(exc))
                await asyncio.sleep(settings.poll_interval_sec)

    async def _run_one(self, job: Any) -> None:
        """下载输入 + 执行单个任务。"""
        settings = get_settings()

        if not job.input_presigned_url:
            LOG.warning("worker.no_presigned_url", job_id=job.job_id)
            async with make_sessionmaker()() as session:
                await mark_failed(
                    session, job.job_id, error={"message": "missing input_presigned_url"}
                )
            return

        contents = settings.workspace_dir / job.job_id / "contents"
        try:
            await load_input(
                job.input_presigned_url,
                job.input_object_key,
                contents,
                timeout=settings.http_timeout_sec,
            )
        except Exception as exc:  # noqa: BLE001
            LOG.exception("worker.input_load_failed", job_id=job.job_id, error=str(exc))
            async with make_sessionmaker()() as session:
                await mark_failed(
                    session, job.job_id, error={"message": f"input load failed: {exc}"}
                )
            return

        await run_job(job, contents)
