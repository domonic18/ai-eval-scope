"""任务执行器 -- 打包、评估、按提交者身份回传、更新 eval_jobs 状态。

与 gateway/worker/runner.py 的差异：
- 输入不再来自 ``job.input_ref``（本地路径），而由调用方传入已下载物化的 ``input_dir``；
- 工作区落 ``settings.workspace_dir/<job_id>``（原 upload_dir/workspaces）；
- 状态机 ``mark_running`` 移至 entrypoint/loop（启动第一时间置 running）。
"""

from __future__ import annotations

import asyncio
import traceback
from dataclasses import replace
from pathlib import Path
from typing import Any

from agent_eval.evaluation.registry import registry
from agent_eval.observability import ResultSink, load_config
from agent_eval.orchestrator import eval_packages

from eval_executor.auth.crypto import decrypt_token
from eval_executor.auth.repo import find_api_key_by_id
from eval_executor.config.settings import get_settings
from eval_executor.core.exceptions import LegacyJobRejectedError, RuleSetNotFoundError
from eval_executor.core.logging import get_logger
from eval_executor.executor.builder import build_package
from eval_executor.models.db import EvalJob
from eval_executor.queue.jobs import mark_done, mark_failed
from eval_executor.storage.session import make_sessionmaker

LOG = get_logger(__name__)

# 可观测性回传（ResultSink.flush）的有界超时：best-effort，不让回传阻塞任务完成。
FLUSH_TIMEOUT_SEC = 60.0


def _resolve_rule_set_path(job: EvalJob) -> str:
    """按 job.package_ref 解析规则集文件路径（S2-C）。

    - 缺失 package_ref → 历史 job，拒绝（LegacyJobRejectedError，不再用 _BUILTIN 回退）。
    - 本地（builtin + 缓存）解析；未命中且配置了 ``AGENT_EVAL_REGISTRY_URL`` → 拉取后重解析。
    - 包内规则集：优先 job.rule_set_id，其次包清单 default_rule_set（courseware=coursework-vision），
      再次包内唯一规则集，否则报错。
    """
    from agent_eval.core.exceptions import ScenarioPackageNotFoundError
    from agent_eval.packages import PackageManager, PackageStore
    from agent_eval.packages.remote_client import get_remote_client

    ref = job.package_ref
    if not ref:
        raise LegacyJobRejectedError(job.job_id)

    pm = PackageManager()
    try:
        pkg = pm.resolve_ref(ref)
    except ScenarioPackageNotFoundError:
        # 本地未命中：配置了远端则拉取后重解析，否则原样抛出
        client = get_remote_client()
        if client is None:
            raise
        remote_pkg = client.fetch(ref)
        PackageStore().install(remote_pkg.manifest, dict(remote_pkg.files))
        pkg = pm.resolve_ref(ref)

    rules_dir = pkg.rules_dir
    # 回退链：job 显式指定 → 包清单 default_rule_set → 包 id（与规则集同名时）
    name = job.rule_set_id or pkg.manifest.default_rule_set or pkg.manifest.id
    path = rules_dir / f"{name}.yaml"
    if path.exists():
        return str(path)
    avail = sorted(p.stem for p in rules_dir.glob("*.yaml"))
    if len(avail) == 1:
        return str(rules_dir / f"{avail[0]}.yaml")
    if not avail:
        raise RuleSetNotFoundError(f"{ref}（包内无规则集）")
    raise RuleSetNotFoundError(f"{ref}（包内规则集不明确，请指定 rule_set_id：{avail}）")


def _eval_meta(result: Any, job: EvalJob, rule_set_path: str) -> dict[str, Any]:
    """构建评估透明度元数据：所需能力 + 实际就绪 + 被跳过的评估器。"""
    import agent_eval.evaluation.evaluators  # noqa: F401  触发注册
    from agent_eval.config.loader import ConfigLoader
    from agent_eval.core.types import Capability
    from agent_eval.evaluation.capability import CapabilityResolver

    required_caps: list[str] = []
    try:
        rs = ConfigLoader.load_rule_set(rule_set_path)
        required_caps = sorted(
            c.value for c in CapabilityResolver(registry).resolve(rs).capabilities
        )
    except Exception as exc:  # noqa: BLE001
        LOG.warning("eval_meta.resolve_failed", job_id=job.job_id, error=str(exc))

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

    provisioned = [c for c in required_caps if c != Capability.VISION.value or not skipped]
    return {
        "capabilities": {"required": required_caps, "provisioned": provisioned},
        "skipped": skipped,
    }


async def _resolve_submit_token(job: EvalJob) -> str | None:
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


async def refresh_input_url(job: EvalJob) -> str | None:
    """领取后向 web 重签输入下载 URL（以提交者身份）。

    提交时签发的 presigned URL 受 presignTtlSec 上限约束（≤15min，§十三）；队列积压或
    前序长任务会把它拖过期——MinIO 回 403，任务失败为「input load failed」。
    任一环节失败返回 None，调用方回退 job.input_presigned_url（可能仍有效）。
    """
    try:
        token = await _resolve_submit_token(job)
        if not token:
            return None
        cfg = load_config()
        if not cfg.host:
            return None
        import httpx

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{cfg.host}/api/v1/jobs/{job.job_id}/input-url",
                headers={"Authorization": f"Bearer {token}"},
            )
        if resp.status_code == 200:
            url = (resp.json() or {}).get("url")
            if isinstance(url, str) and url:
                LOG.info("input.url_refreshed", job_id=job.job_id)
                return url
        LOG.warning("input.url_refresh_bad_status", job_id=job.job_id, status_code=resp.status_code)
    except Exception as exc:  # noqa: BLE001 — 刷新失败回退原 URL，不阻断任务
        LOG.warning("input.url_refresh_failed", job_id=job.job_id, error=str(exc)[:200])
    return None


def _flush_result(
    result: Any,
    package_dir: Path,
    job: EvalJob,
    token: str | None,
    job_output_dir: Path,
) -> Any:
    """以「提交者身份」回传评估结果到 Web（per-job config）。"""
    if not token:
        return None  # 无可用凭据 → 跳过回传，评估结果仍存 eval_jobs.metrics

    base_cfg = load_config(upload_override=True)  # 读 AGENT_EVAL_HOST 等
    per_job_cfg = replace(
        base_cfg,
        api_key=token,
        project=job.project_id,
        queue_dir=job_output_dir / ".ingest_queue",
        # enabled 是 load_config 依据 env AGENT_EVAL_API_KEY 算出的派生字段；per-job token
        # 覆盖 api_key 后必须同步重算，否则 ResultSink.flush 会静默跳过回传。
        enabled=base_cfg.upload and bool(token),
    )
    sink = ResultSink(per_job_cfg)
    run_workspace = result.run_workspace.root if result.run_workspace else None
    return sink.flush(result, run_workspace=run_workspace, package_dir=package_dir)


def _file_patterns_from_rule_set(rule_set_path: str | Path | None) -> list[str]:
    """从规则集 format 门控推导要收集的文件类型（code→*.py / courseware→*.html,*.md）。

    与 /debug 的 accept 同源（规则集 rules[].extensions）；无 format 门控或缺规则集
    → 回退 ["*"] 全收，由 format 门控兜底校验。
    """
    if not rule_set_path:
        return ["*"]
    try:
        import yaml

        data = yaml.safe_load(Path(rule_set_path).read_text(encoding="utf-8")) or {}
        exts: set[str] = set()
        for rule in data.get("rules") or []:
            if (
                isinstance(rule, dict)
                and rule.get("method") == "format"
                and isinstance(rule.get("extensions"), list)
            ):
                exts.update(str(e).lstrip(".") for e in rule["extensions"])
        return [f"*.{e}" for e in sorted(exts)] or ["*"]
    except Exception:
        return ["*"]


async def _notify_web_completion(job_id: str, token: str | None) -> None:
    """job 完成/失败后通知 web → web 异步投递 webhook 回调。best-effort（失败仅日志）。"""
    if not token:
        return
    try:
        cfg = load_config()
        if not cfg.host:
            return
        import httpx

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{cfg.host}/api/v1/jobs/{job_id}/notify-completion",
                headers={"Authorization": f"Bearer {token}"},
            )
        LOG.info("job.notified", job_id=job_id, status_code=resp.status_code)
    except Exception as exc:  # noqa: BLE001
        LOG.warning("job.notify_failed", job_id=job_id, error=str(exc))


async def run_job(job: EvalJob, input_dir: Path) -> None:
    """执行单个任务（input_dir 为已下载物化的输入目录）。"""
    settings = get_settings()
    job_output_dir = settings.workspace_dir / job.job_id
    package_dir = job_output_dir / "package"
    token: str | None = None

    try:
        rule_set_path = _resolve_rule_set_path(job)

        build_package(
            input_dir=input_dir,
            package_dir=package_dir,
            task_id=job.task_id,
            task_title=job.task_title or job.job_id,
            task_subject=job.task_subject,
            file_patterns=_file_patterns_from_rule_set(rule_set_path),
        )

        result = await asyncio.to_thread(
            eval_packages,
            package_dir=package_dir,
            rule_set_path=rule_set_path,
            output_dir=job_output_dir / "workspace",
            project=job.project_id,
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
        # 透明度：把能力需求 + 被跳过的评估器折进 metrics._executor，供 GET /api/v1/jobs/:id 回显。
        metrics["_executor"] = _eval_meta(result, job, rule_set_path)
        web_run_url = f"{settings.web_base_url}/run/{result.run_id}"
        async with make_sessionmaker()() as session:
            await mark_done(
                session,
                job.job_id,
                run_id=result.run_id,
                metrics=metrics,
                web_run_url=web_run_url,
            )
        # 通知 web → 投递 webhook 回调（best-effort）
        await _notify_web_completion(job.job_id, token)
    except Exception as exc:  # noqa: BLE001
        LOG.exception("job.execution_failed", job_id=job.job_id, error=str(exc))
        error = {
            "message": str(exc),
            "traceback": traceback.format_exc(),
        }
        async with make_sessionmaker()() as session:
            await mark_failed(session, job.job_id, error=error)
        # 失败也通知（token 可能在异常前已解析，best-effort）
        await _notify_web_completion(job.job_id, token)
