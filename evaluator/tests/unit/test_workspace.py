"""Workspace 管理测试。"""

import json
from pathlib import Path

import pytest

from agent_eval.core.exceptions import WorkspaceError
from agent_eval.storage.workspace import RunWorkspace, Workspace


@pytest.fixture
def tmp_workspace(tmp_path: Path) -> Workspace:
    """创建临时 Workspace 实例。"""
    return Workspace(root_dir=tmp_path / "workspace")


class TestWorkspace:
    def test_ensure_dirs(self, tmp_workspace: Workspace) -> None:
        tmp_workspace.ensure_dirs()
        assert tmp_workspace.root.exists()
        assert tmp_workspace.runs_dir.exists()
        assert tmp_workspace.cache_dir.exists()
        assert tmp_workspace.index_dir.exists()

    def test_exists(self, tmp_workspace: Workspace) -> None:
        assert not tmp_workspace.exists
        tmp_workspace.ensure_dirs()
        assert tmp_workspace.exists

    def test_create_run(self, tmp_workspace: Workspace) -> None:
        run_ws = tmp_workspace.create_run("20260609_100000")
        assert run_ws.run_id == "20260609_100000"
        assert run_ws.root.exists()
        assert run_ws.packages_dir.exists()
        assert run_ws.results_dir.exists()
        assert run_ws.reports_dir.exists()

    def test_create_run_auto_id(self, tmp_workspace: Workspace) -> None:
        run_ws = tmp_workspace.create_run()
        assert run_ws.run_id  # 应该自动生成
        assert len(run_ws.run_id) > 0

    def test_get_run(self, tmp_workspace: Workspace) -> None:
        tmp_workspace.create_run("20260609_100000")
        run_ws = tmp_workspace.get_run("20260609_100000")
        assert run_ws.run_id == "20260609_100000"

    def test_get_run_not_found(self, tmp_workspace: Workspace) -> None:
        with pytest.raises(WorkspaceError):
            tmp_workspace.get_run("nonexistent")

    def test_list_runs(self, tmp_workspace: Workspace) -> None:
        tmp_workspace.create_run("run_a")
        tmp_workspace.create_run("run_b")
        runs = tmp_workspace.list_runs()
        assert len(runs) == 2

    def test_cleanup(self, tmp_workspace: Workspace) -> None:
        for i in range(5):
            tmp_workspace.create_run(f"run_{i}")
        deleted = tmp_workspace.cleanup(keep_recent=2)
        assert len(deleted) == 3
        assert len(tmp_workspace.list_runs()) == 2

    def test_cleanup_no_delete(self, tmp_workspace: Workspace) -> None:
        tmp_workspace.create_run("run_a")
        deleted = tmp_workspace.cleanup(keep_recent=10)
        assert len(deleted) == 0


class TestRunWorkspace:
    def test_write_run_manifest(self, tmp_path: Path) -> None:
        run_ws = RunWorkspace(root=tmp_path / "run_001", run_id="run_001")
        run_ws.ensure_dirs()
        run_ws.write_run_manifest({"mode": "eval-only"})

        manifest_path = tmp_path / "run_001" / "run_manifest.json"
        assert manifest_path.exists()
        data = json.loads(manifest_path.read_text())
        assert data["run_id"] == "run_001"
        assert data["mode"] == "eval-only"

    def test_get_package_dir(self, tmp_path: Path) -> None:
        run_ws = RunWorkspace(root=tmp_path / "run", run_id="run")
        assert run_ws.get_package_dir("task_01") == tmp_path / "run" / "packages" / "task_01"

    def test_get_result_dir(self, tmp_path: Path) -> None:
        run_ws = RunWorkspace(root=tmp_path / "run", run_id="run")
        assert run_ws.get_result_dir("task_01") == tmp_path / "run" / "results" / "task_01"

    def test_list_packages_empty(self, tmp_path: Path) -> None:
        run_ws = RunWorkspace(root=tmp_path / "run", run_id="run")
        run_ws.ensure_dirs()
        assert run_ws.list_packages() == []

    def test_list_results_empty(self, tmp_path: Path) -> None:
        run_ws = RunWorkspace(root=tmp_path / "run", run_id="run")
        run_ws.ensure_dirs()
        assert run_ws.list_results() == []
