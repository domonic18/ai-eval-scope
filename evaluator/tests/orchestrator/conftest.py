"""Orchestrator 测试 fixtures。"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from agent_eval.storage.workspace import RunWorkspace, Workspace

FIXTURES = Path(__file__).parent.parent / "fixtures"


@pytest.fixture
def workspace(tmp_path: Path) -> Workspace:
    """创建临时 Workspace。"""
    ws = Workspace(root_dir=tmp_path / "workspace")
    ws.ensure_dirs()
    return ws


@pytest.fixture
def run_workspace(workspace: Workspace) -> RunWorkspace:
    """创建临时 RunWorkspace。"""
    return workspace.create_run("20260609_120000")


@pytest.fixture
def golden_package(tmp_path: Path) -> Path:
    """从 golden 样本构建 ExecutionPackage 并写入 tmp_path。"""
    golden_dir = FIXTURES / "golden" / "valid_docset"
    pkg_dir = tmp_path / "packages" / "task_001"
    pkg_dir.mkdir(parents=True)

    # 复制 golden 样本到 output
    output_dir = pkg_dir / "output"
    output_dir.mkdir()
    for f in golden_dir.rglob("*"):
        if f.is_file():
            rel = f.relative_to(golden_dir)
            target = pkg_dir / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(f.read_bytes())

    # 写入 manifest.json
    manifest = {
        "package_id": "pkg_test_001",
        "created_at": "2026-06-09T12:00:00+00:00",
        "task_id": "task_001",
        "sut_config_id": "manual",
        "status": "success",
    }
    (pkg_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # 写入 task.json
    task_data = {
        "id": "task_001",
        "input": {"title": "一元一次方程"},
        "constraints": {},
    }
    (pkg_dir / "task.json").write_text(
        json.dumps(task_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # 写入 metadata.json
    metadata = {"sut_name": "manual", "eval_system_version": "0.1.0"}
    (pkg_dir / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return pkg_dir


@pytest.fixture
def mock_judge_orchestrator() -> MagicMock:
    """Mock JudgeOrchestrator。"""
    return MagicMock()
