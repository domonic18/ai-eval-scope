"""任务相关路由 — 提交 / 查询 / 取消。"""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, status
from fastapi.exceptions import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.datastructures import UploadFile

from eval_gateway.auth.deps import Tenant, verify_api_key
from eval_gateway.config.settings import get_settings
from eval_gateway.core.exceptions import InputInvalidError
from eval_gateway.core.logging import get_logger
from eval_gateway.core.types import InputKind, JobStatus
from eval_gateway.models.db import Job
from eval_gateway.models.schemas import JobResponse, JobSubmissionResponse
from eval_gateway.queue.jobs import enqueue, get_job, mark_cancelled
from eval_gateway.storage.session import get_async_session
from eval_gateway.storage.workspace import materialize_inline, materialize_upload

LOG = get_logger(__name__)
router = APIRouter(prefix="/v1/jobs", tags=["jobs"])


def _cleanup(temp_dir: Path) -> None:
    shutil.rmtree(temp_dir, ignore_errors=True)


@router.post("", response_model=JobSubmissionResponse, status_code=status.HTTP_202_ACCEPTED)
async def submit_job(
    request: Request,
    tenant: Annotated[Tenant, Depends(verify_api_key)],
    session: Annotated[AsyncSession, Depends(get_async_session)],
) -> JobSubmissionResponse:
    """提交评估任务（multipart 上传 或 application/json 内联）。

    按 Content-Type 手动解析，避免 FastAPI 混合 File+Body 参数的解析限制。
    """
    content_type = request.headers.get("content-type", "")
    settings = get_settings()
    job_id = str(uuid.uuid4())
    temp_dir = settings.upload_dir / "pending" / job_id
    temp_dir.mkdir(parents=True, exist_ok=True)

    try:
        if content_type.startswith("multipart/form-data"):
            form = await request.form()
            upload = form.get("file")
            if not isinstance(upload, UploadFile) or upload.filename is None:
                raise InputInvalidError("file is required for multipart upload")
            rule_set_id_raw = form.get("rule_set_id")
            rule_set_id = rule_set_id_raw if isinstance(rule_set_id_raw, str) else "coursework-default"
            input_ref, scope = await materialize_upload(
                upload, temp_dir, max_size=settings.max_upload_mb * 1024 * 1024
            )
            input_kind = InputKind.UPLOAD.value
        elif content_type.startswith("application/json"):
            try:
                data: dict[str, Any] = await request.json()
            except Exception as exc:  # noqa: BLE001
                raise InputInvalidError("invalid JSON body") from exc
            content = data.get("content")
            if not isinstance(content, dict):
                raise InputInvalidError("content required")
            rule_set_id_raw = data.get("rule_set_id")
            rule_set_id = rule_set_id_raw if isinstance(rule_set_id_raw, str) else "coursework-default"
            input_ref, scope = materialize_inline(content, temp_dir)
            input_kind = InputKind.INLINE.value
        else:
            raise InputInvalidError(f"unsupported content-type: {content_type}")

        await enqueue(
            session,
            tenant,
            job_id=job_id,
            input_kind=input_kind,
            scope=scope.value,
            input_ref=input_ref,
            rule_set_id=rule_set_id,
        )

        poll_url = f"/v1/jobs/{job_id}"
        LOG.info("job.submitted", job_id=job_id, project_id=tenant.project_id, scope=scope.value)
        return JobSubmissionResponse(
            job_id=job_id,
            status=JobStatus.QUEUED,
            web_run_url=None,
            poll_url=poll_url,
        )
    except Exception:
        _cleanup(temp_dir)
        raise


@router.get("/{job_id}", response_model=JobResponse)
async def get_job_status(
    job_id: str,
    tenant: Annotated[Tenant, Depends(verify_api_key)],
    session: Annotated[AsyncSession, Depends(get_async_session)],
) -> Job:
    """查询任务状态。"""
    job = await get_job(session, job_id, tenant)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "job not found", "code": "JOB_NOT_FOUND"},
        )
    return job


@router.post("/{job_id}/cancel")
async def cancel_job(
    job_id: str,
    tenant: Annotated[Tenant, Depends(verify_api_key)],
    session: Annotated[AsyncSession, Depends(get_async_session)],
) -> dict[str, str]:
    """取消任务（仅 queued 态可取消）。"""
    job = await get_job(session, job_id, tenant)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "job not found", "code": "JOB_NOT_FOUND"},
        )
    ok = await mark_cancelled(session, job_id)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "cannot cancel job", "code": "CANCEL_FAILED"},
        )
    return {"job_id": job_id, "status": "failed", "message": "cancelled"}
