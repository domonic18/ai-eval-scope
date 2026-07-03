"""任务执行器 — 打包、评估、按提交者身份回传、更新 jobs 状态。"""

from __future__ import annotations

import asyncio
import traceback
from dataclasses import replace
from pathlib import Path
from typing import Any

from agent_eval.config.paths import paths as agent_eval_paths
from agent_eval.evaluation.registry import registry
from agent_eval.observability import ResultSink, load_config
from agent_eval.orchestrator import eval_packages

from eval_gateway.auth.crypto import decrypt_token
from eval_gateway.auth.repo import find_api_key_by_id
from eval_gateway.config.settings import get_settings
from eval_gateway.core.logging import get_logger
from eval_gateway.models.db import Job
from eval_gateway.queue.jobs import mark_done, mark_failed
from eval_gateway.storage.session import make_sessionmaker
from eval_gateway.worker.builder import build_package

LOG = get_logger(__name__)

# 可观测性回传（ResultSink.flush）的有界超时：best-effort，不让回传阻塞任务完成。
FLUSH_TIMEOUT_SEC = 60.0

# gateway 自带规则集资源目录（仅 format-only 等内置资源定位用；规则集解析走 registry）
_ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"


def _rule_set_path(rule_set_id: str) -> str:
    """规则集标识 → 文件路径（经注册表查找；未知 id 回退默认，保持向后兼容）。

    docs/arch/13 §3.7：规则集作为一等资源，替代原硬编码 2 分支逻辑。
    """
    from eval_gateway.rules.registry import get_path

    path = get_path(rule_set_id)
    if path is None:
        # 未知 id：回退默认规则集（不破坏存量调用），并记录便于排查
        LOG.warning("rule_set.unknown_id_fallback", rule_set_id=rule_set_id)
        path = agent_eval_paths.rules_dir / "default_rule_set.yaml"
    return str(path)


def _llm_config_path() -> str | None:
    """评估器 LLM 配置路径（自动发现 llm_config.yaml）。"""
    cfg = agent_eval_paths.configs_dir / "llm_config.yaml"
    return str(cfg) if cfg.exists() else None


def _eval_meta(result: Any, job: Job) -> dict[str, Any]:
    """构建评估透明度元数据：所需能力 + 实际就绪 + 被跳过的评估器。

    - capabilities.required：规则集派生（CapabilityResolver）
    - capabilities.provisioned：本次实际启用（视觉取决于是否建了渲染器；保守按 required∩已跑）
    - skipped：从评估结果里扫 status=skip 的约束（尽力而为，结构缺失则空）
    """
    import agent_eval.evaluation.evaluators  # noqa: F401  触发注册
    from agent_eval.core.types import Capability
    from agent_eval.evaluation.capability import CapabilityResolver

    rule_set_path = _rule_set_path(job.rule_set_id)
    required_caps: list[str] = []
    try:
        from agent_eval.config.loader import ConfigLoader

        rs = ConfigLoader.load_rule_set(rule_set_path)
        required_caps = sorted(
            c.value for c in CapabilityResolver(registry).resolve(rs).capabilities
        )
    except Exception as exc:  # noqa: BLE001
        LOG.warning("eval_meta.resolve_failed", job_id=job.job_id, error=str(exc))

    # 被跳过的评估器：扫描 sample_scores / constraints 中 status=skip（尽力）
    skipped: list[dict[str, Any]] = []
    try:
        report = getattr(result, "report", None)
        samples = getattr(report, "sample_scores", None) or []
        for s in samples:
            for c in (
                getattr(s, "constraints", None) or getattr(s, "constraint_results", None) or []
            ):
                status = getattr(c, "status", None)
                status_val = getattr(status, "value", status)
                if str(status_val).lower() == "skip":
                    skipped.append(
                        {
                            "evaluator": getattr(c, "constraint_id", None),
                            "reason": getattr(c, "reason", ""),
                        }
                    )
    except Exception as exc:  # noqa: BLE001
        LOG.warning("eval_meta.skipped_extract_failed", job_id=job.job_id, error=str(exc))

    # provisioned：required 中视觉是否真跑了（无独立标记，按未出现在 skipped 估算）
    provisioned = [c for c in required_caps if c != Capability.VISION.value or not skipped]
    return {
        "capabilities": {"required": required_caps, "provisioned": provisioned},
        "skipped": skipped,
    }


async def _resolve_submit_token(job: Job) -> str | None:
    """按 job.api_key_id 查提交者 API Key，解密得明文 token；Key 不存在/已吊销返回 None。"""
    settings = get_settings()
    async with make_sessionmaker()() as session:
        key = await find_api_key_by_id(session, job.api_key_id)
    if key is None or key.revoked_at is not None:
        LOG.warning("job.flush.no_key", job_id=job.job_id, api_key_id=job.api_key_id)
        return None
    try:
        return decrypt_token(key.token_encrypted, settings.key_encryption_key)
    except Exception as exc:  # noqa: BLE001
        LOG.warning("job.flush.decrypt_failed", job_id=job.job_id, error=str(exc))
        return None


def _flush_result(
    result: Any,
    package_dir: Path,
    job: Job,
    token: str | None,
    job_output_dir: Path,
) -> Any:
    """以「提交者身份」回传评估结果到 Web（per-job config）。

    - 用提交者的 token（Bearer）回传 → web 按该 token 绑定的项目落库 = 第三方项目。
    - host/超时/重试 等仍取部署 env（AGENT_EVAL_HOST）；api_key/project/queue_dir per-job 覆盖。
    - 队列目录绑定到本 job 工作区：回传失败的事件不被跨 job 重放（best-effort，§5.6）。

    返回 SinkReport（供调用方记录回传结果）；无凭据时返回 None。
    """
    if not token:
        return None  # 无可用凭据（Key 已删/吊销）→ 跳过回传，评估结果仍存 jobs.metrics

    base_cfg = load_config(upload_override=True)  # 读 AGENT_EVAL_HOST 等
    per_job_cfg = replace(
        base_cfg,
        api_key=token,
        project=job.project_id,
        queue_dir=job_output_dir / ".ingest_queue",  # per-job 临时队列，不跨 job 重放
        # enabled 是 load_config 依据 env AGENT_EVAL_API_KEY 算出的派生字段；gateway 用 per-job
        # token 覆盖 api_key 后必须同步重算 —— 否则部署未配 AGENT_EVAL_API_KEY 时 base_cfg.enabled
        # 恒为 False，ResultSink.flush 会静默跳过回传（run 不落 web，且无任何报错）。
        enabled=base_cfg.upload and bool(token),
    )
    sink = ResultSink(per_job_cfg)
    run_workspace = result.run_workspace.root if result.run_workspace else None
    return sink.flush(result, run_workspace=run_workspace, package_dir=package_dir)


async def run_job(job: Job) -> None:
    """执行单个任务。"""
    settings = get_settings()
    job_output_dir = settings.upload_dir / "workspaces" / job.job_id
    package_dir = job_output_dir / "package"

    try:
        input_dir = Path(job.input_ref)
        # task_id 不填时 builder 回退为目录名（单页恒为 "contents"）；调用方可经 HTTP 设 task_id 覆盖。
        build_package(
            input_dir=input_dir,
            package_dir=package_dir,
            task_id=job.task_id,
            task_title=job.task_title or job.job_id,
            task_subject=job.task_subject,
        )

        result = await asyncio.to_thread(
            eval_packages,
            package_dir=package_dir,
            rule_set_path=_rule_set_path(job.rule_set_id),
            output_dir=job_output_dir / "workspace",
            project=job.project_id,
            llm_config_path=_llm_config_path(),
        )

        # 按 job 提交者身份回传（per-job token + project）→ 结果落到第三方项目
        token = await _resolve_submit_token(job)
        try:
            report = await asyncio.wait_for(
                asyncio.to_thread(_flush_result, result, package_dir, job, token, job_output_dir),
                timeout=FLUSH_TIMEOUT_SEC,
            )
            if report is None:
                LOG.warning("job.flush.skipped_no_credential", job_id=job.job_id)
            elif not report.enabled:
                LOG.warning("job.flush.skipped_disabled", job_id=job.job_id)
            elif report.error:
                LOG.warning(
                    "job.flush.error",
                    job_id=job.job_id,
                    error=report.error,
                    sent=report.sent,
                    queued=report.queued,
                )
            else:
                LOG.info(
                    "job.flush.ok",
                    job_id=job.job_id,
                    sent=report.sent,
                    queued=report.queued,
                    artifacts=report.artifacts_uploaded,
                )
        except Exception as exc:  # noqa: BLE001
            LOG.warning("job.flush.best_effort_failed", job_id=job.job_id, error=str(exc))

        metrics = result.report.to_dict()
        # 透明度（docs/arch/13 §3.9）：把能力需求 + 被跳过的评估器折进 metrics._gateway，
        # 供 GET /v1/jobs/{id} 显式回显（HTTP 调用方看不到进程日志，杜绝静默失真）。
        metrics["_gateway"] = _eval_meta(result, job)
        web_run_url = f"{settings.web_base_url}/run/{result.run_id}"
        async with make_sessionmaker()() as session:
            await mark_done(
                session,
                job.job_id,
                run_id=result.run_id,
                metrics=metrics,
                web_run_url=web_run_url,
            )
    except Exception as exc:  # noqa: BLE001
        LOG.exception("job.execution_failed", job_id=job.job_id, error=str(exc))
        error = {
            "message": str(exc),
            "traceback": traceback.format_exc(),
        }
        async with make_sessionmaker()() as session:
            await mark_failed(session, job.job_id, error=error)
