"""Workspace 索引重建 — 供 Web Portal 与 CLI `agent-eval index` 使用。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    """原子写入 JSON 文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _load_project_configs(assets_dir: Path) -> list[dict[str, Any]]:
    """从 assets/projects/*.yaml 加载项目配置。"""
    projects_dir = assets_dir / "projects"
    projects: list[dict[str, Any]] = []
    if not projects_dir.exists():
        return projects

    for file in sorted(projects_dir.glob("*.yaml")):
        try:
            raw = yaml.safe_load(file.read_text(encoding="utf-8")) or {}
            data = raw.get("project", raw)
            project_id = data.get("id") or file.stem
            projects.append(
                {
                    "id": project_id,
                    "name": data.get("name", project_id),
                    "description": data.get("description", ""),
                    "default_rule_set": data.get("default_rule_set", ""),
                    "default_task_set": data.get("default_task_set", ""),
                    "created_at": data.get("created_at", ""),
                    "latest_run_id": None,
                    "run_count": 0,
                }
            )
        except Exception:
            # 跳过无效项目配置
            continue
    return projects


def _scan_runs(runs_dir: Path) -> list[dict[str, Any]]:
    """扫描 workspace/runs 目录，重建 runs_index。"""
    runs: list[dict[str, Any]] = []
    if not runs_dir.exists():
        return runs

    for run_dir in sorted(runs_dir.iterdir(), reverse=True):
        if not run_dir.is_dir():
            continue
        summary_path = run_dir / "reports" / "summary.json"
        manifest_path = run_dir / "run_manifest.json"
        if not summary_path.exists():
            continue

        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            manifest = {}
            if manifest_path.exists():
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

            runs.append(
                {
                    "run_id": summary.get("run_id", run_dir.name),
                    "mode": manifest.get("mode", "unknown"),
                    "total_samples": summary.get("total_samples", 0),
                    "metrics": summary.get("metrics", {}),
                    "failure_breakdown": summary.get("failure_breakdown", {}),
                    "created_at": manifest.get("created_at", ""),
                    "project": manifest.get("project"),
                }
            )
        except Exception:
            continue

    return runs


def _cross_reference_projects(projects: list[dict[str, Any]], runs: list[dict[str, Any]]) -> None:
    """根据 runs 计算每个项目的 run_count 和 latest_run_id。"""
    proj_map = {p["id"]: p for p in projects}
    for run in runs:
        project_id = run.get("project")
        if project_id and project_id in proj_map:
            proj = proj_map[project_id]
            proj["run_count"] += 1
            if proj["latest_run_id"] is None:
                proj["latest_run_id"] = run["run_id"]


def rebuild_index(workspace_dir: Path | str) -> dict[str, Any]:
    """重建 workspace 索引。

    生成 workspace/index/projects.json 与 workspace/index/runs_index.json。

    Args:
        workspace_dir: workspace 根目录。

    Returns:
        统计信息 dict：{"project_count": int, "run_count": int}
    """
    workspace = Path(workspace_dir).resolve()
    index_dir = workspace / "index"
    runs_dir = workspace / "runs"
    assets_dir = workspace.parent / "assets"

    runs = _scan_runs(runs_dir)
    projects = _load_project_configs(assets_dir)
    _cross_reference_projects(projects, runs)

    _atomic_write_json(index_dir / "runs_index.json", {"runs": runs})
    _atomic_write_json(index_dir / "projects.json", {"projects": projects})

    return {
        "project_count": len(projects),
        "run_count": len(runs),
    }
