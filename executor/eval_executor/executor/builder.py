"""打包逻辑 — 从物化目录构造 ExecutionPackage，复用 evaluator PackageBuilder。"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from agent_eval.orchestrator import eval_packages  # noqa: F401

from eval_executor.core.logging import get_logger

LOG = get_logger(__name__)


# 注意：agent_eval.execution.models 与 config.loader 存在循环导入。
# 先 import agent_eval.orchestrator 预热后再局部 import Task/PackageBuilder，可绕开。


def build_package(
    input_dir: Path,
    package_dir: Path,
    *,
    task_title: str | None = None,
    task_subject: str | None = None,
    task_id: str | None = None,
    file_patterns: list[str] | None = None,
) -> Path:
    """把物化目录打包为标准 ExecutionPackage。"""
    # 局部导入，避免 evaluator 内部循环导入问题
    from agent_eval.execution.models import Task
    from agent_eval.storage.builder import PackageBuilder

    if task_id is None:
        task_id = input_dir.name or "task"
    title = task_title or task_id
    task_input: dict[str, Any] = {"title": title}
    if task_subject:
        task_input["subject"] = task_subject

    # file_patterns 由调用方按规则集 format 门控推导（code→*.py / courseware→*.html,*.md）；
    # 缺省全收 ["*"]，由 format 门控兜底校验（去 courseware html/md 硬编码）。
    task = Task(
        id=task_id,
        input=task_input,
        file_patterns=file_patterns or ["*"],
    )
    content_hash = _content_hash(input_dir)

    package_dir.mkdir(parents=True, exist_ok=True)
    builder = PackageBuilder()
    builder.build_directory(
        task=task,
        source_dir=input_dir,
        package_dir=package_dir,
        content_hash=content_hash,
    )
    LOG.info(
        "package.built", package_dir=str(package_dir), task_id=task_id, content_hash=content_hash
    )
    return package_dir


def _content_hash(source_dir: Path) -> str | None:
    """计算目录内容的稳定短哈希（SHA256 前 8 位）。

    从 evaluator cli/main.py:36-58 复制，保证与 pack CLI 行为一致。
    """
    h = hashlib.sha256()
    files = sorted(
        p
        for p in source_dir.rglob("*")
        if p.is_file() and not any(part.startswith(".") for part in p.relative_to(source_dir).parts)
    )
    if not files:
        return None
    for p in files:
        h.update(p.relative_to(source_dir).as_posix().encode("utf-8"))
        h.update(b"\x00")
        h.update(p.read_bytes())
        h.update(b"\x00")
    return h.hexdigest()[:8]
