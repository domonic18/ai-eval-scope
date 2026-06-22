"""Workspace 管理 — 目录创建、路径解析、生命周期管理。

Workspace 是运行时的文件系统工作空间，结构如下：
    workspace/
    ├── runs/{run_id}/       # 各次运行的输出
    ├── datasets/            # 评测数据集（agent-eval dataset download 下载）
    ├── index/               # Web Portal 索引
    └── cache/               # 跨运行共享缓存
"""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agent_eval.config.paths import paths
from agent_eval.core.exceptions import WorkspaceError
from agent_eval.storage.package import generate_run_id


class Workspace:
    """Workspace 管理器。

    管理运行时工作空间的目录结构创建、路径解析和生命周期。
    """

    def __init__(self, root_dir: Path | str | None = None) -> None:
        """初始化 Workspace。

        Args:
            root_dir: 工作空间根目录路径，默认为 ./workspace。
        """
        self.root = Path(root_dir) if root_dir else paths.default_workspace
        self.runs_dir = self.root / "runs"
        self.cache_dir = self.root / "cache"
        self.index_dir = self.root / "index"
        self.datasets_dir = self.root / "datasets"

    @property
    def exists(self) -> bool:
        """检查 Workspace 根目录是否存在。"""
        return self.root.exists()

    def ensure_dirs(self) -> None:
        """确保 Workspace 目录结构存在。"""
        self.root.mkdir(parents=True, exist_ok=True)
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.index_dir.mkdir(parents=True, exist_ok=True)
        self.datasets_dir.mkdir(parents=True, exist_ok=True)

    def create_run(self, run_id: str | None = None) -> RunWorkspace:
        """创建一次运行的工作空间。

        Args:
            run_id: 运行 ID（时间戳格式），不传则自动生成。

        Returns:
            RunWorkspace 实例。
        """
        self.ensure_dirs()
        if run_id is None:
            run_id = generate_run_id()

        run_ws = RunWorkspace(
            root=self.runs_dir / run_id,
            run_id=run_id,
        )
        run_ws.ensure_dirs()
        return run_ws

    def get_run(self, run_id: str) -> RunWorkspace:
        """获取已有的运行工作空间。

        Args:
            run_id: 运行 ID。

        Returns:
            RunWorkspace 实例。

        Raises:
            WorkspaceError: 运行目录不存在。
        """
        run_dir = self.runs_dir / run_id
        if not run_dir.exists():
            raise WorkspaceError(f"运行目录不存在: {run_dir}")
        return RunWorkspace(root=run_dir, run_id=run_id)

    def list_runs(self) -> list[str]:
        """列出所有运行 ID（按时间倒序）。"""
        if not self.runs_dir.exists():
            return []
        runs = sorted(
            [d.name for d in self.runs_dir.iterdir() if d.is_dir()],
            reverse=True,
        )
        return runs

    def cleanup(self, keep_recent: int = 10) -> list[str]:
        """清理历史运行，仅保留最近 N 次。

        Args:
            keep_recent: 保留的最近运行数。

        Returns:
            被删除的运行 ID 列表。
        """
        runs = self.list_runs()
        if len(runs) <= keep_recent:
            return []

        to_delete = runs[keep_recent:]
        deleted: list[str] = []
        for run_id in to_delete:
            run_dir = self.runs_dir / run_id
            try:
                shutil.rmtree(run_dir)
                deleted.append(run_id)
            except OSError as e:
                raise WorkspaceError(f"删除运行目录失败: {run_dir}: {e}") from e

        return deleted


class RunWorkspace:
    """单次运行的工作空间。

    目录结构:
        runs/{run_id}/
        ├── run_manifest.json
        ├── packages/{task_id}/
        ├── results/{task_id}/
        ├── reports/
        └── agent_logs/
    """

    def __init__(self, root: Path, run_id: str) -> None:
        self.root = root
        self.run_id = run_id
        self.packages_dir = root / "packages"
        self.results_dir = root / "results"
        self.reports_dir = root / "reports"
        self.agent_logs_dir = root / "agent_logs"

    def ensure_dirs(self) -> None:
        """确保运行目录结构存在。"""
        self.root.mkdir(parents=True, exist_ok=True)
        self.packages_dir.mkdir(parents=True, exist_ok=True)
        self.results_dir.mkdir(parents=True, exist_ok=True)
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        self.agent_logs_dir.mkdir(parents=True, exist_ok=True)

    def get_package_dir(self, task_id: str) -> Path:
        """获取指定任务的执行包目录。"""
        return self.packages_dir / task_id

    def get_result_dir(self, task_id: str) -> Path:
        """获取指定任务的评估结果目录。"""
        return self.results_dir / task_id

    def write_run_manifest(self, metadata: dict[str, Any] | None = None) -> None:
        """写入运行 manifest。"""
        manifest = {
            "run_id": self.run_id,
            "created_at": datetime.now(UTC).isoformat(),
            **(metadata or {}),
        }
        (self.root / "run_manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def list_packages(self) -> list[str]:
        """列出所有执行包的 task_id。"""
        if not self.packages_dir.exists():
            return []
        return [d.name for d in self.packages_dir.iterdir() if d.is_dir()]

    def list_results(self) -> list[str]:
        """列出所有评估结果的 task_id。"""
        if not self.results_dir.exists():
            return []
        return [d.name for d in self.results_dir.iterdir() if d.is_dir()]
