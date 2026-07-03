"""API 路由端到端测试 — httpx.AsyncClient + mock 鉴权/DB/worker。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from httpx import AsyncClient

from eval_gateway.core.types import JobStatus
from eval_gateway.models.db import Job


async def test_health(client: AsyncClient) -> None:
    response = await client.get("/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


async def test_submit_multipart(
    client: AsyncClient,
    fake_session: MagicMock,
) -> None:
    """multipart 上传提交任务应返回 202 与 job_id。"""
    fake_session.add = MagicMock()
    fake_session.commit = AsyncMock()
    fake_session.refresh = AsyncMock()

    files = {"file": ("lesson.md", b"# Hello", "text/markdown")}
    data = {"task_title": "分数入门", "rule_set_id": "format-only"}
    response = await client.post("/v1/jobs", data=data, files=files)

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == JobStatus.QUEUED.value
    assert body["job_id"]
    assert body["poll_url"].startswith("/v1/jobs/")
    # 归属由 API Key 验签解析（tenant），调用方不在请求体传 project_id
    assert body["project_id"] == "project-1"
    assert body["org_id"] == "org-1"
    fake_session.add.assert_called_once()


async def test_submit_inline_json(
    client: AsyncClient,
    fake_session: MagicMock,
) -> None:
    """内联 JSON 提交任务应返回 202。"""
    fake_session.add = MagicMock()
    fake_session.commit = AsyncMock()
    fake_session.refresh = AsyncMock()

    payload = {
        "content": {"filename": "lesson.md", "text": "# Hello"},
        "task_title": "分数入门",
        "rule_set_id": "format-only",
    }
    response = await client.post("/v1/jobs", json=payload)

    assert response.status_code == 202
    assert response.json()["status"] == JobStatus.QUEUED.value


async def test_get_job_status(
    client: AsyncClient,
    fake_session: MagicMock,
    tenant: Tenant,
) -> None:
    """查询任务状态应返回 job 信息。"""
    expected_job = Job(
        job_id="job-1",
        project_id=tenant.project_id,
        org_id=tenant.org_id,
        status=JobStatus.COMPLETED.value,
        input_kind="upload",
        scope="single",
        input_ref="/tmp",
        rule_set_id="format-only",
        run_id="run-1",
        metrics={"dr": 0.9},
    )
    fake_session.execute = AsyncMock()
    fake_session.execute.return_value.scalar_one_or_none = MagicMock(return_value=expected_job)

    response = await client.get("/v1/jobs/job-1")
    assert response.status_code == 200
    body = response.json()
    assert body["job_id"] == "job-1"
    assert body["status"] == JobStatus.COMPLETED.value


async def test_get_job_not_found(
    client: AsyncClient,
    fake_session: MagicMock,
) -> None:
    fake_session.execute = AsyncMock()
    fake_session.execute.return_value.scalar_one_or_none = MagicMock(return_value=None)

    response = await client.get("/v1/jobs/not-exist")
    assert response.status_code == 404


async def test_cancel_job(
    client: AsyncClient,
    fake_session: MagicMock,
    tenant: Tenant,
) -> None:
    expected_job = Job(
        job_id="job-1",
        project_id=tenant.project_id,
        org_id=tenant.org_id,
        status=JobStatus.QUEUED.value,
        input_kind="upload",
        scope="single",
        input_ref="/tmp",
        rule_set_id="format-only",
    )
    fake_session.execute = AsyncMock()
    fake_session.execute.return_value.scalar_one_or_none = MagicMock(return_value=expected_job)
    fake_session.execute.return_value.rowcount = 1
    fake_session.commit = AsyncMock()

    response = await client.post("/v1/jobs/job-1/cancel")
    assert response.status_code == 200


async def test_submit_multipart_passes_task_fields(
    client: AsyncClient,
    fake_session: MagicMock,
) -> None:
    """提交时携带 task_id/task_title/task_subject 应写入入队 Job（不再恒为 contents）。"""
    added: list[Job] = []
    fake_session.add = MagicMock(side_effect=lambda job: added.append(job))
    fake_session.commit = AsyncMock()
    fake_session.refresh = AsyncMock()

    files = {"file": ("lesson.md", b"# Hello", "text/markdown")}
    data = {
        "task_id": "my-task-001",
        "task_title": "分数入门",
        "task_subject": "math",
        "rule_set_id": "format-only",
    }
    response = await client.post("/v1/jobs", data=data, files=files)

    assert response.status_code == 202
    assert len(added) == 1
    job = added[0]
    assert job.task_id == "my-task-001"
    assert job.task_title == "分数入门"
    assert job.task_subject == "math"


async def test_submit_inline_json_passes_task_id(
    client: AsyncClient,
    fake_session: MagicMock,
) -> None:
    """内联 JSON 提交携带 task_id 应写入 Job。"""
    added: list[Job] = []
    fake_session.add = MagicMock(side_effect=lambda job: added.append(job))
    fake_session.commit = AsyncMock()
    fake_session.refresh = AsyncMock()

    payload = {
        "content": {"filename": "lesson.md", "text": "# Hello"},
        "task_id": "lesson-3",
        "rule_set_id": "format-only",
    }
    response = await client.post("/v1/jobs", json=payload)

    assert response.status_code == 202
    assert added[0].task_id == "lesson-3"
    assert added[0].task_title is None


# Tenant 类型提示
from eval_gateway.auth.deps import Tenant  # noqa: E402


async def test_list_rule_sets(client: AsyncClient) -> None:
    """GET /v1/rule-sets 返回内置规则集目录，含派生能力。"""
    response = await client.get("/v1/rule-sets")
    assert response.status_code == 200
    items = response.json()["rule_sets"]
    ids = {item["id"] for item in items}
    # 三个递进 coursework tier + format-only
    assert {"coursework-gate", "coursework-quality", "coursework-vision", "format-only"} == ids
    # 每项含 capabilities（派生）+ scopes
    for item in items:
        assert "capabilities" in item
        assert "scopes" in item
    # 能力递进：format-only 无；gate/quality 仅 llm；vision 含 llm+vision
    assert next(i for i in items if i["id"] == "format-only")["capabilities"] == []
    assert next(i for i in items if i["id"] == "coursework-gate")["capabilities"] == ["llm"]
    assert next(i for i in items if i["id"] == "coursework-quality")["capabilities"] == ["llm"]
    assert next(i for i in items if i["id"] == "coursework-vision")["capabilities"] == [
        "llm",
        "vision",
    ]
