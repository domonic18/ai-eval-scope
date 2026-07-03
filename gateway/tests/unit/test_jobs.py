"""queue/jobs 状态机单元测试 — 用 mock session 断言 SQL 与状态流转。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from eval_gateway.auth.deps import Tenant
from eval_gateway.core.types import InputKind, JobStatus, Scope
from eval_gateway.models.db import Job
from eval_gateway.queue import jobs as jobs_queue


@pytest.fixture
def tenant() -> Tenant:
    return Tenant(
        api_key_id="ak-1",
        project_id="project-1",
        org_id="org-1",
        scopes=["ingest"],
    )


async def test_enqueue_adds_job(fake_session: MagicMock, tenant: Tenant) -> None:
    fake_session.refresh = AsyncMock(return_value=None)
    fake_session.commit = AsyncMock(return_value=None)

    job = await jobs_queue.enqueue(
        fake_session,
        tenant,
        job_id="job-1",
        input_kind=InputKind.UPLOAD.value,
        scope=Scope.UNIT.value,
        input_ref="/tmp/job-1",
        rule_set_id="coursework-quality",
    )

    assert job.job_id == "job-1"
    assert job.status == JobStatus.QUEUED.value
    fake_session.add.assert_called_once()
    fake_session.commit.assert_awaited_once()


async def test_mark_done_updates_status(fake_session: MagicMock) -> None:
    fake_session.execute = AsyncMock(return_value=MagicMock(rowcount=1))
    fake_session.commit = AsyncMock(return_value=None)

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
    fake_session.commit = AsyncMock(return_value=None)

    await jobs_queue.mark_failed(fake_session, "job-1", error={"message": "boom"})

    fake_session.execute.assert_awaited_once()
    fake_session.commit.assert_awaited_once()


async def test_get_job_filters_by_tenant(fake_session: MagicMock, tenant: Tenant) -> None:
    expected_job = Job(
        job_id="job-1",
        project_id=tenant.project_id,
        org_id=tenant.org_id,
        status=JobStatus.COMPLETED.value,
        input_kind=InputKind.UPLOAD.value,
        scope=Scope.UNIT.value,
        input_ref="/tmp",
        rule_set_id="coursework-quality",
    )
    fake_session.execute = AsyncMock()
    fake_session.execute.return_value.scalar_one_or_none = MagicMock(return_value=expected_job)

    job = await jobs_queue.get_job(fake_session, "job-1", tenant)

    assert job is expected_job


async def test_get_job_wrong_tenant_returns_none(fake_session: MagicMock, tenant: Tenant) -> None:
    other_job = Job(
        job_id="job-1",
        project_id="project-other",
        org_id="org-other",
        status=JobStatus.COMPLETED.value,
        input_kind=InputKind.UPLOAD.value,
        scope=Scope.UNIT.value,
        input_ref="/tmp",
        rule_set_id="coursework-quality",
    )
    fake_session.execute = AsyncMock()
    fake_session.execute.return_value.scalar_one_or_none = MagicMock(return_value=other_job)

    job = await jobs_queue.get_job(fake_session, "job-1", tenant)
    assert job is None


async def test_mark_cancelled_only_queued(fake_session: MagicMock) -> None:
    fake_session.execute = AsyncMock(return_value=MagicMock(rowcount=1))
    fake_session.commit = AsyncMock(return_value=None)
    assert await jobs_queue.mark_cancelled(fake_session, "job-1")

    fake_session.execute = AsyncMock(return_value=MagicMock(rowcount=0))
    assert not await jobs_queue.mark_cancelled(fake_session, "job-1")
