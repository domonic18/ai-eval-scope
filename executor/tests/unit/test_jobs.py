"""queue/jobs 状态机单元测试 — 用 mock session 断言 SQL 与状态流转。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from eval_executor.core.types import InputKind, JobStatus, Scope
from eval_executor.models.db import EvalJob
from eval_executor.queue import jobs as jobs_queue


def _make_job(**overrides: object) -> EvalJob:
    base: dict[str, object] = dict(
        job_id="job-1",
        api_key_id="ak-1",
        project_id="project-1",
        org_id="org-1",
        status=JobStatus.QUEUED.value,
        input_kind=InputKind.UPLOAD.value,
        scope=Scope.UNIT.value,
        input_object_key="projects/project-1/eval/jobs/job-1/input.zip",
        rule_set_id="coursework-quality",
    )
    base.update(overrides)
    return EvalJob(**base)  # type: ignore[arg-type]


async def test_claim_returns_and_marks_running(fake_session: MagicMock) -> None:
    fake_session.execute = AsyncMock(
        return_value=MagicMock(first=MagicMock(return_value=("job-1",)))
    )
    fake_session.get = AsyncMock(return_value=_make_job())
    fake_session.refresh = AsyncMock(return_value=None)

    job = await jobs_queue.claim(fake_session)

    assert job is not None
    assert job.status == JobStatus.RUNNING.value
    fake_session.commit.assert_awaited_once()


async def test_claim_none_when_queue_empty(fake_session: MagicMock) -> None:
    fake_session.execute = AsyncMock(return_value=MagicMock(first=MagicMock(return_value=None)))
    assert await jobs_queue.claim(fake_session) is None


async def test_mark_running_updates(fake_session: MagicMock) -> None:
    fake_session.execute = AsyncMock(return_value=MagicMock(rowcount=1))
    assert await jobs_queue.mark_running(fake_session, "job-1") is True
    fake_session.commit.assert_awaited_once()


async def test_mark_running_skipped_when_not_queued(fake_session: MagicMock) -> None:
    fake_session.execute = AsyncMock(return_value=MagicMock(rowcount=0))
    assert await jobs_queue.mark_running(fake_session, "job-1") is False


async def test_mark_done_updates_status(fake_session: MagicMock) -> None:
    fake_session.execute = AsyncMock(return_value=MagicMock(rowcount=1))

    await jobs_queue.mark_done(
        fake_session,
        "job-1",
        run_id="run-1",
        metrics={"dr": 0.9},
        web_run_url="http://web/runs/run-1",
    )

    fake_session.execute.assert_awaited_once()
    fake_session.commit.assert_awaited_once()


async def test_mark_failed_updates_status(fake_session: MagicMock) -> None:
    fake_session.execute = AsyncMock(return_value=MagicMock(rowcount=1))

    await jobs_queue.mark_failed(fake_session, "job-1", error={"message": "boom"})

    fake_session.execute.assert_awaited_once()
    fake_session.commit.assert_awaited_once()


async def test_get_job_returns_job(fake_session: MagicMock) -> None:
    expected = _make_job()
    fake_session.execute = AsyncMock()
    fake_session.execute.return_value.scalar_one_or_none = MagicMock(return_value=expected)

    assert await jobs_queue.get_job(fake_session, "job-1") is expected


async def test_get_job_missing_returns_none(fake_session: MagicMock) -> None:
    fake_session.execute = AsyncMock()
    fake_session.execute.return_value.scalar_one_or_none = MagicMock(return_value=None)

    assert await jobs_queue.get_job(fake_session, "missing") is None
