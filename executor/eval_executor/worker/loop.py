"""Worker 主循环 -- 本地 worker 模式（无 SCF event 时轮询 eval_jobs，本地开发用）。

生产模式由 SCF 事件函数触发（每次 Invoke 执行一个 job），不走此循环。

并发语义：每轮先持信号量再 claim（无空位不领取，避免任务被抢占后长时间滞留 running），
领取后以独立 task 执行，signal 量在任务结束时释放——同一时刻最多 concurrency 个任务在跑。
此前实现为循环内 await 单任务，信号量形同虚设，实际串行：一个长任务会把后续任务全部
堵成 queued，拖到提交时签发的 presigned URL 过期（input load failed 403）。
"""

from __future__ import annotations

import asyncio
from typing import Any

from eval_executor.config.settings import get_settings
from eval_executor.core.logging import get_logger
from eval_executor.executor.runner import refresh_input_url, run_job
from eval_executor.queue.jobs import claim, mark_failed
from eval_executor.storage.input_loader import load_input
from eval_executor.storage.session import make_sessionmaker

LOG = get_logger(__name__)


class WorkerLoop:
    """本地 worker 模式：轮询 queued 任务，并发执行。"""

    def __init__(self, concurrency: int = 2) -> None:
        self.concurrency = concurrency
        self._sem = asyncio.Semaphore(concurrency)
        self._tasks: set[asyncio.Task[None]] = set()
        self._running = False

    async def run(self) -> None:
        """阻塞运行 worker 循环（entrypoint worker 模式入口）。"""
        self._running = True
        LOG.info("worker.started", concurrency=self.concurrency)
        settings = get_settings()
        while self._running:
            try:
                # 先持信号量再 claim：保证「领取即执行」，不做无空位的提前抢占
                await self._sem.acquire()
                try:
                    async with make_sessionmaker()() as session:
                        job = await claim(session)
                except BaseException:
                    self._sem.release()
                    raise
                if job is None:
                    self._sem.release()
                    await asyncio.sleep(settings.poll_interval_sec)
                    continue

                task = asyncio.create_task(self._run_one(job))
                self._tasks.add(task)
                task.add_done_callback(self._tasks.discard)
            except asyncio.CancelledError:
                break
            except Exception as exc:  # noqa: BLE001
                LOG.exception("worker.loop.error", error=str(exc))
                await asyncio.sleep(settings.poll_interval_sec)
        # 退出前等在途任务收尾（状态回写/通知），避免容器停止时任务被硬切成「僵尸 running」
        if self._tasks:
            try:
                await asyncio.gather(*self._tasks, return_exceptions=True)
            except asyncio.CancelledError:
                pass

    async def _run_one(self, job: Any) -> None:
        """下载输入 + 执行单个任务（结束时释放信号量）。"""
        try:
            settings = get_settings()

            # 领取时先重签 URL（提交时签发的可能已过期）；刷新失败回退 job 上的原 URL
            url = await refresh_input_url(job) or job.input_presigned_url
            if not url:
                LOG.warning("worker.no_presigned_url", job_id=job.job_id)
                async with make_sessionmaker()() as session:
                    await mark_failed(
                        session, job.job_id, error={"message": "missing input_presigned_url"}
                    )
                return

            contents = settings.workspace_dir / job.job_id / "contents"
            try:
                await load_input(
                    url, job.input_object_key, contents, timeout=settings.http_timeout_sec
                )
            except Exception as exc:  # noqa: BLE001
                LOG.exception("worker.input_load_failed", job_id=job.job_id, error=str(exc))
                async with make_sessionmaker()() as session:
                    await mark_failed(
                        session, job.job_id, error={"message": f"input load failed: {exc}"}
                    )
                return

            await run_job(job, contents)
        finally:
            self._sem.release()
