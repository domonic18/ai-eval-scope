"""worker loop 单元测试 — 并发语义与 _run_one 的 URL 刷新回退链。

回归背景：loop 曾在循环体内 await 单任务，Semaphore 形同虚设、实际串行——一个长任务把
后续任务堵成 queued，拖到提交时签发的 presigned URL 过期（input load failed 403）。
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from eval_executor.worker import loop as loop_mod
from eval_executor.worker.loop import WorkerLoop


def _job(job_id: str = "job-1", url: str | None = "http://minio:9000/old?sig=1") -> MagicMock:
    job = MagicMock()
    job.job_id = job_id
    job.input_object_key = f"projects/p/eval/jobs/{job_id}/input.md"
    job.input_presigned_url = url
    return job


@pytest.fixture
def loop() -> WorkerLoop:
    return WorkerLoop(concurrency=2)


# ── _run_one：URL 刷新回退链 ──────────────────────────────────────────


async def test_run_one_prefers_refreshed_url(
    loop: WorkerLoop, fake_sessionmaker: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """刷新成功 → 用新 URL 下载输入并执行。"""
    job = _job()
    monkeypatch.setattr(loop_mod, "refresh_input_url", AsyncMock(return_value="http://fresh?sig=2"))
    monkeypatch.setattr(loop_mod, "load_input", AsyncMock())
    monkeypatch.setattr(loop_mod, "run_job", AsyncMock())

    await loop._run_one(job)

    loop_mod.load_input.assert_awaited_once()
    assert loop_mod.load_input.call_args.args[0] == "http://fresh?sig=2"
    loop_mod.run_job.assert_awaited_once()
    assert loop_mod.run_job.call_args.args[0] is job


async def test_run_one_falls_back_to_job_url(
    loop: WorkerLoop, fake_sessionmaker: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """刷新失败（None）→ 回退 job.input_presigned_url，任务照常执行。"""
    job = _job(url="http://old?sig=1")
    monkeypatch.setattr(loop_mod, "refresh_input_url", AsyncMock(return_value=None))
    monkeypatch.setattr(loop_mod, "load_input", AsyncMock())
    monkeypatch.setattr(loop_mod, "run_job", AsyncMock())

    await loop._run_one(job)

    assert loop_mod.load_input.call_args.args[0] == "http://old?sig=1"
    loop_mod.run_job.assert_awaited_once()


async def test_run_one_marks_failed_without_any_url(
    loop: WorkerLoop, fake_sessionmaker: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """刷新失败且 job 无 URL → mark_failed（missing input_presigned_url），不执行。"""
    job = _job(url=None)
    mark_failed = AsyncMock()
    monkeypatch.setattr(loop_mod, "mark_failed", mark_failed)
    monkeypatch.setattr(loop_mod, "refresh_input_url", AsyncMock(return_value=None))
    monkeypatch.setattr(loop_mod, "load_input", AsyncMock())
    monkeypatch.setattr(loop_mod, "run_job", AsyncMock())

    await loop._run_one(job)

    mark_failed.assert_awaited_once()
    assert "missing input_presigned_url" in mark_failed.call_args.kwargs["error"]["message"]
    loop_mod.run_job.assert_not_awaited()


async def test_run_one_marks_failed_on_load_error(
    loop: WorkerLoop, fake_sessionmaker: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """下载失败（如 URL 过期 403）→ mark_failed（input load failed），不执行。"""
    job = _job()
    mark_failed = AsyncMock()
    monkeypatch.setattr(loop_mod, "mark_failed", mark_failed)
    monkeypatch.setattr(loop_mod, "refresh_input_url", AsyncMock(return_value="http://fresh"))
    monkeypatch.setattr(loop_mod, "load_input", AsyncMock(side_effect=RuntimeError("403 expired")))
    monkeypatch.setattr(loop_mod, "run_job", AsyncMock())

    await loop._run_one(job)

    mark_failed.assert_awaited_once()
    assert "input load failed" in mark_failed.call_args.kwargs["error"]["message"]
    loop_mod.run_job.assert_not_awaited()


async def test_run_one_releases_semaphore(
    loop: WorkerLoop, fake_sessionmaker: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """任务结束（含早退分支）必须归还信号量，否则并发槽位泄漏、loop 停摆。"""
    monkeypatch.setattr(loop_mod, "mark_failed", AsyncMock())
    monkeypatch.setattr(loop_mod, "refresh_input_url", AsyncMock(return_value=None))
    job = _job(url=None)  # 走 mark_failed 早退分支

    await loop._sem.acquire()  # 模拟 run() 在 claim 前的获取
    assert loop._sem._value == 1  # type: ignore[attr-defined]

    await loop._run_one(job)

    assert loop._sem._value == 2  # type: ignore[attr-defined]  # 归还，无泄漏


# ── run()：真并发（回归核心用例）──────────────────────────────────────


async def test_worker_loop_runs_jobs_concurrently(
    fake_sessionmaker: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """两个任务同时在跑（回归：旧实现串行时此用例超时失败）。"""
    loop = WorkerLoop(concurrency=2)
    pending = [_job("job-1"), _job("job-2")]
    active = 0
    both_running = asyncio.Event()

    async def fake_claim(_session: Any) -> MagicMock | None:
        if pending:
            return pending.pop(0)
        loop._running = False  # 两个任务都已领取 → 让循环退出
        return None

    async def fake_run_job(_job: object, _contents: object) -> None:
        nonlocal active
        active += 1
        if active >= 2:
            both_running.set()
        await asyncio.wait_for(both_running.wait(), timeout=2)
        active -= 1

    monkeypatch.setattr(loop_mod, "claim", fake_claim)
    monkeypatch.setattr(loop_mod, "refresh_input_url", AsyncMock(return_value="http://fresh"))
    monkeypatch.setattr(loop_mod, "load_input", AsyncMock())
    monkeypatch.setattr(loop_mod, "run_job", fake_run_job)

    await asyncio.wait_for(loop.run(), timeout=5)

    assert both_running.is_set()


async def test_worker_loop_claim_error_releases_semaphore(
    fake_sessionmaker: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """claim 抛错 → 信号量归还且循环继续（不因一次 DB 抖动停摆）。"""
    loop = WorkerLoop(concurrency=2)
    calls = {"n": 0}

    async def fake_claim(_session: Any) -> None:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("db glitch")
        loop._running = False
        return None

    monkeypatch.setattr(loop_mod, "claim", fake_claim)

    await asyncio.wait_for(loop.run(), timeout=5)

    assert calls["n"] == 2
    assert loop._sem._value == 2  # type: ignore[attr-defined]
