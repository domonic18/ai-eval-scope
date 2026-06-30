"""任务执行器 — 打包、评估、显式回传、更新 jobs 状态。"""

from __future__ import annotations

import asyncio
import traceback
from pathlib import Path
from typing import Any

from agent_eval.config.paths import paths as agent_eval_paths
from agent_eval.observability import ResultSink, load_config
from agent_eval.orchestrator import eval_packages

from eval_gateway.config.settings import get_settings
from eval_gateway.core.logging import get_logger
from eval_gateway.models.db import Job
from eval_gateway.queue.jobs import mark_done, mark_failed
from eval_gateway.storage.session import make_sessionmaker
from eval_gateway.worker.builder import build_package

LOG = get_logger(__name__)

# gateway 自带规则集资源目录
_ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"


def _rule_set_path(rule_set_id: str) -> str:
    """规则集标识 → 文件路径。"""
    if rule_set_id == "format-only":
        # 纯格式规则集，gateway 自带，用于 CI/冒烟（无 LLM 依赖）
        return str(_ASSETS_DIR / "rules" / "format_only.yaml")
    # 默认课件规则集（可能含 LLM Judge）
    return str(agent_eval_paths.rules_dir / "default_rule_set.yaml")


def _flush_result(result: Any, package_dir: Path) -> None:
    """显式把评估结果回传到 Web 可观测平台（同步阻塞，须在线程调用）。"""
    cfg = load_config(upload_override=True)
    sink = ResultSink(cfg)
    run_workspace = result.run_workspace.root if result.run_workspace else None
    sink.flush(result, run_workspace=run_workspace, package_dir=package_dir)


async def run_job(job: Job) -> None:
    """执行单个任务。"""
    settings = get_settings()
    job_output_dir = settings.upload_dir / "workspaces" / job.job_id
    package_dir = job_output_dir / "package"

    try:
        input_dir = Path(job.input_ref)
        build_package(input_dir=input_dir, package_dir=package_dir, task_title=job.job_id)

        result = await asyncio.to_thread(
            eval_packages,
            package_dir=package_dir,
            rule_set_path=_rule_set_path(job.rule_set_id),
            output_dir=job_output_dir / "workspace",
            project=job.project_id,
        )

        await asyncio.to_thread(_flush_result, result, package_dir)

        metrics = result.report.to_dict()
        web_run_url = f"{settings.web_base_url}/projects/{job.project_id}/runs/{result.run_id}"
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
