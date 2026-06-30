"""Worker 主循环 — FastAPI startup 启动的 asyncio task。"""

from __future__ import annotations

import asyncio
from typing import Any

from eval_gateway.config.settings import get_settings
from eval_gateway.core.logging import get_logger
from eval_gateway.queue.jobs import claim
from eval_gateway.storage.session import make_sessionmaker
from eval_gateway.worker.runner import run_job

LOG = get_logger(__name__)


class WorkerLoop:
    """PG 持久化队列 worker：轮询 queued 任务，并发执行。"""

    def __init__(self, concurrency: int = 2) -> None:
        self.concurrency = concurrency
        self._task: asyncio.Task[Any] | None = None
        self._sem = asyncio.Semaphore(concurrency)
        self._running = False

    def start(self) -> None:
        """启动 worker task。"""
        if self._task is not None:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        LOG.info("worker.started", concurrency=self.concurrency)

    async def stop(self) -> None:
        """优雅停止。"""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        LOG.info("worker.stopped")

    async def _loop(self) -> None:
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
                    await run_job(job)
            except asyncio.CancelledError:
                break
            except Exception as exc:  # noqa: BLE001
                LOG.exception("worker.loop.error", error=str(exc))
                await asyncio.sleep(settings.poll_interval_sec)
