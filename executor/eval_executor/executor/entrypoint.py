"""SCF 事件函数 / 本地 worker 入口。

部署形态：腾讯云 SCF「事件函数 + Job 镜像 + 异步执行」（timeout ≤ 24h）。
事件经 ``SCF_CUSTOM_CONTAINER_EVENT`` 环境变量注入。

三种触发：
- SCF 模式：``SCF_CUSTOM_CONTAINER_EVENT`` 注入事件（含 job_id）→ 读 job 执行单任务后退出。
- 本地调试：``EVALEXECUTOR_JOB_JSON`` 注入单个事件（无需真实 SCF）。
- worker 模式：``EVALEXECUTOR_WORKER_ENABLED=true`` → 轮询 eval_jobs（本地开发）。
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any

from eval_executor.config.settings import get_settings
from eval_executor.core.logging import get_logger, setup_logging
from eval_executor.executor.runner import refresh_input_url, run_job
from eval_executor.queue.jobs import get_job, mark_failed, mark_running
from eval_executor.storage.input_loader import load_input
from eval_executor.storage.session import make_sessionmaker

LOG = get_logger(__name__)


def _parse_event() -> dict[str, Any] | None:
    """解析 SCF 事件（SCF_CUSTOM_CONTAINER_EVENT 或本地 EVALEXECUTOR_JOB_JSON）。"""
    raw = os.getenv("SCF_CUSTOM_CONTAINER_EVENT") or os.getenv("EVALEXECUTOR_JOB_JSON")
    if not raw:
        return None
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        LOG.warning("entrypoint.event_parse_failed", raw=raw[:200])
        return None


async def _run_single_job(event: dict[str, Any]) -> None:
    """SCF 模式：执行单个 job。"""
    job_id = event.get("job_id")
    if not isinstance(job_id, str) or not job_id:
        LOG.error("entrypoint.no_job_id", event_data=event)
        return

    settings = get_settings()

    # 第一时间置 running，缩小「SCF 已触发但状态仍 queued」的卡死窗口
    async with make_sessionmaker()() as session:
        ok = await mark_running(session, job_id)
        job = await get_job(session, job_id)

    if job is None:
        LOG.error("entrypoint.job_not_found", job_id=job_id)
        return
    if not ok:
        LOG.warning("entrypoint.mark_running_skipped", job_id=job_id, status=job.status)

    # 下载输入（领取即重签——SCF invoke 延迟也可能拖过期提交时签发的 URL；
    # 刷新失败回退事件里的 URL，再回退 job 记录里的 presigned URL）
    url = (
        await refresh_input_url(job) or event.get("input_presigned_url") or job.input_presigned_url
    )
    contents = settings.workspace_dir / job_id / "contents"
    contents.mkdir(parents=True, exist_ok=True)
    try:
        if not url:
            raise RuntimeError("missing input_presigned_url")
        await load_input(url, job.input_object_key, contents, timeout=settings.http_timeout_sec)
    except Exception as exc:  # noqa: BLE001
        LOG.exception("entrypoint.input_load_failed", job_id=job_id, error=str(exc))
        async with make_sessionmaker()() as session:
            await mark_failed(session, job_id, error={"message": f"input load failed: {exc}"})
        return

    await run_job(job, contents)


async def _run_worker() -> None:
    """worker 模式：轮询 eval_jobs。"""
    from eval_executor.worker.loop import WorkerLoop

    loop = WorkerLoop(concurrency=get_settings().worker_concurrency)
    await loop.run()


def _inject_platform_secrets() -> None:
    """启动时拉取平台 Secrets 注入进程 env（W4，arch/16 §2.4）。

    executor 无状态、无交互入口：org 级凭证（SUT 账号等）经页面录入，
    启动时经 ``GET /api/public/secrets``（Bearer AGENT_EVAL_API_KEY）拉取解密
    KV 注入 ``os.environ``——评估器的 CredentialStore env 通道零改动读到。
    未配置通道或拉取失败：警告降级，不阻断启动（本地开发无平台时正常跑）。
    """
    host = os.getenv("AGENT_EVAL_HOST", "").rstrip("/")
    api_key = os.getenv("AGENT_EVAL_API_KEY", "")
    if not host or not api_key:
        LOG.info("secrets.inject.skipped_no_channel")
        return
    try:
        import httpx

        resp = httpx.get(
            f"{host}/api/public/secrets",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10.0,
        )
        resp.raise_for_status()
        data = resp.json().get("secrets") or {}
        os.environ.update(data)
        LOG.info("secrets.inject.ok", count=len(data))  # 只记数量，不记名称与值
    except Exception as e:  # noqa: BLE001 — 注入失败不阻断启动
        LOG.warning("secrets.inject.failed", error=str(e)[:200])


def main() -> None:
    """容器入口。"""
    setup_logging()
    _inject_platform_secrets()
    event = _parse_event()
    if event is not None:
        asyncio.run(_run_single_job(event))
        return
    if get_settings().worker_enabled:
        asyncio.run(_run_worker())
        return
    LOG.info("entrypoint.no_event_no_worker")


if __name__ == "__main__":
    main()
