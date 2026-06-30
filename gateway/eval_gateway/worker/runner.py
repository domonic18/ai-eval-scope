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

# 可观测性回传（ResultSink.flush）的有界超时：制品 presigned 上传失败时会指数退避重试，
# 可能耗时数分钟；gateway 不能让它阻塞任务完成（评估结果以本地 report 为准）。
FLUSH_TIMEOUT_SEC = 60.0

# gateway 自带规则集资源目录
_ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"


def _rule_set_path(rule_set_id: str) -> str:
    """规则集标识 → 文件路径。"""
    if rule_set_id == "format-only":
        # 纯格式规则集，gateway 自带，用于 CI/冒烟（无 LLM 依赖）
        return str(_ASSETS_DIR / "rules" / "format_only.yaml")
    # 默认课件规则集（含 LLM Judge：常识/软约束/偏好）
    return str(agent_eval_paths.rules_dir / "default_rule_set.yaml")


def _llm_config_path() -> str | None:
    """评估器 LLM 配置路径（自动发现 llm_config.yaml）。

    ``eval_packages`` 不会自动发现 LLM 配置——不传则所有 LLM 规则被跳过（llm_skipped）。
    故这里显式定位评估器自带配置；文件不存在（如纯格式场景/未配置 key）返回 None。
    """
    cfg = agent_eval_paths.configs_dir / "llm_config.yaml"
    return str(cfg) if cfg.exists() else None


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

        # 可观测性回传 best-effort + 有界超时：评估结果以本地 report 为准，
        # 不让 flush（如制品 presigned 上传重试）阻塞任务完成；失败交离线队列择机重放。
        try:
            await asyncio.wait_for(
                asyncio.to_thread(_flush_result, result, package_dir),
                timeout=FLUSH_TIMEOUT_SEC,
            )
        except Exception as exc:  # noqa: BLE001
            LOG.warning("job.flush.best_effort_failed", job_id=job.job_id, error=str(exc))

        metrics = result.report.to_dict()
        # web 前端运行详情路由为 /run/:id（见 web/frontend/src/App.tsx），且 web 侧 runGuard/
        # runDetail 既按内部 UUID 解析、也兜底按 external_run_id（评估器 run_id）解析。
        # gateway 只知道评估器的 external run_id，故用它构造链接。
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
