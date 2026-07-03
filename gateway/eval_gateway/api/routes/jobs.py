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
from eval_gateway.models.schemas import JobResponse, JobSubmissionResponse
from eval_gateway.queue.jobs import enqueue, get_job, mark_cancelled
from eval_gateway.storage.session import get_async_session
from eval_gateway.storage.workspace import materialize_inline, materialize_upload

LOG = get_logger(__name__)
router = APIRouter(prefix="/v1/jobs", tags=["jobs"])


def _cleanup(temp_dir: Path) -> None:
    shutil.rmtree(temp_dir, ignore_errors=True)


def _str_field(form: Any, key: str) -> str | None:
    """从 multipart 表单取字符串字段（UploadFile/None → None）。"""
    val = form.get(key)
    return val if isinstance(val, str) else None


def _vision_provisioned() -> bool:
    """gateway 镜像是否具备视觉能力（playwright 包 + Chromium 二进制的轻量探测）。"""
    try:
        import playwright  # noqa: F401  包级探测
    except Exception:  # noqa: BLE001
        return False
    # 二进制存在性探测：renderer 启动时才真正校验，这里做路径存在性快速判断
    try:
        from playwright._impl._driver import (
            compute_driver_executable,  # type: ignore[import-not-found]
        )
    except Exception:  # noqa: BLE001
        return True  # 探测接口不可用时退化为「包已装即视为就绪」，留给运行时校验
    try:
        from pathlib import Path

        node, driver = compute_driver_executable()
        return Path(driver).exists()
    except Exception:  # noqa: BLE001
        return True


def _assert_capabilities_provisioned(rule_set_id: str) -> None:
    """规则集所需能力不可达 → 422（strict，docs/arch/13 §3.9）。"""
    from eval_gateway.rules.registry import get_path

    path = get_path(rule_set_id)
    if path is None:
        return  # 未知 id 由 runner 回退默认，此处不阻断
    try:
        import agent_eval.evaluation.evaluators  # noqa: F401  触发注册
        from agent_eval.config.loader import ConfigLoader
        from agent_eval.core.types import Capability
        from agent_eval.evaluation.capability import CapabilityResolver
        from agent_eval.evaluation.registry import registry as eval_registry

        rule_set = ConfigLoader.load_rule_set(path)
        required = CapabilityResolver(eval_registry).resolve(rule_set)
    except Exception as exc:  # noqa: BLE001  规则集解析失败不阻断提交（runner 会兜底）
        LOG.warning("capability.resolve_failed_at_submit", rule_set_id=rule_set_id, error=str(exc))
        return
    if Capability.VISION in required.capabilities and not _vision_provisioned():
        raise HTTPException(
            status_code=422,
            detail={
                "error": "rule set requires vision capability, but Chromium is not provisioned",
                "code": "CAPABILITY_UNAVAILABLE",
                "hint": "在 gateway 镜像内执行 playwright install chromium，或改用不含视觉评估器的规则集",
                "rule_set_id": rule_set_id,
            },
        )


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
            rule_set_id = (
                rule_set_id_raw if isinstance(rule_set_id_raw, str) else "coursework-default"
            )
            task_id = _str_field(form, "task_id")
            task_title = _str_field(form, "task_title")
            task_subject = _str_field(form, "task_subject")
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
            rule_set_id = (
                rule_set_id_raw if isinstance(rule_set_id_raw, str) else "coursework-default"
            )
            task_id = data.get("task_id") if isinstance(data.get("task_id"), str) else None
            task_title = data.get("task_title") if isinstance(data.get("task_title"), str) else None
            task_subject = (
                data.get("task_subject") if isinstance(data.get("task_subject"), str) else None
            )
            input_ref, scope = materialize_inline(content, temp_dir)
            input_kind = InputKind.INLINE.value
        else:
            raise InputInvalidError(f"unsupported content-type: {content_type}")

        # 能力守卫（docs/arch/13 §3.9）：规则集需要视觉但 gateway 未预装 Chromium →
        # 提交时即 422 拒绝，并给可操作提示，绝不入队一个会静默降级的任务。
        _assert_capabilities_provisioned(rule_set_id)

        await enqueue(
            session,
            tenant,
            job_id=job_id,
            input_kind=input_kind,
            scope=scope.value,
            input_ref=input_ref,
            rule_set_id=rule_set_id,
            task_id=task_id,
            task_title=task_title,
            task_subject=task_subject,
        )

        poll_url = f"/v1/jobs/{job_id}"
        LOG.info("job.submitted", job_id=job_id, project_id=tenant.project_id, scope=scope.value)
        return JobSubmissionResponse(
            job_id=job_id,
            status=JobStatus.QUEUED,
            project_id=tenant.project_id,
            org_id=tenant.org_id,
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
) -> JobResponse:
    """查询任务状态。

    capabilities/skipped 从 metrics._gateway 取出（runner 落库；无 DB 迁移），
    显式暴露实际跑了哪些评估器、哪些被降级跳过（docs/arch/13 §3.9）。
    """
    job = await get_job(session, job_id, tenant)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "job not found", "code": "JOB_NOT_FOUND"},
        )
    resp = JobResponse.model_validate(job, from_attributes=True)
    meta = (job.metrics or {}).get("_gateway") if isinstance(job.metrics, dict) else None
    if isinstance(meta, dict):
        resp.capabilities = meta.get("capabilities")  # type: ignore[assignment]
        resp.skipped = meta.get("skipped")  # type: ignore[assignment]
    return resp


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
