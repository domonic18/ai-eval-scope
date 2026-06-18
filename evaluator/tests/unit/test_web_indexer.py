"""Tests for agent_eval.web.indexer."""

from __future__ import annotations

import json

import pytest
import yaml

from agent_eval.web.indexer import rebuild_index


@pytest.fixture
def sample_workspace(tmp_path):
    """Create a temporary workspace with runs and project config."""
    ws = tmp_path / "workspace"
    runs_dir = ws / "runs"
    index_dir = ws / "index"
    assets_dir = tmp_path / "assets"
    projects_dir = assets_dir / "projects"

    projects_dir.mkdir(parents=True)
    index_dir.mkdir(parents=True)

    # Project config
    project_config = {
        "project": {
            "id": "demo-project",
            "name": "Demo Project",
            "description": "A demo project",
            "default_rule_set": "demo_rules",
            "default_task_set": "demo_tasks",
            "created_at": "2026-06-16T00:00:00Z",
        }
    }
    (projects_dir / "demo-project.yaml").write_text(
        yaml.safe_dump(project_config), encoding="utf-8"
    )

    # Run 1
    run1_dir = runs_dir / "20260616_000001"
    run1_dir.mkdir(parents=True)
    (run1_dir / "run_manifest.json").write_text(
        json.dumps(
            {
                "run_id": "20260616_000001",
                "created_at": "2026-06-16T00:00:01Z",
                "mode": "eval_only",
                "project": "demo-project",
            }
        ),
        encoding="utf-8",
    )
    (run1_dir / "reports").mkdir()
    (run1_dir / "reports" / "summary.json").write_text(
        json.dumps(
            {
                "run_id": "20260616_000001",
                "total_samples": 1,
                "metrics": {
                    "DR": 1.0,
                    "CPR": 0.9,
                    "avg_reward": 1.2,
                    "condR": 1.0,
                    "avg_time_ms": 100,
                },
                "failure_breakdown": {},
            }
        ),
        encoding="utf-8",
    )

    # Run 2
    run2_dir = runs_dir / "20260616_000002"
    run2_dir.mkdir(parents=True)
    (run2_dir / "run_manifest.json").write_text(
        json.dumps(
            {
                "run_id": "20260616_000002",
                "created_at": "2026-06-16T00:00:02Z",
                "mode": "eval_only",
                "project": "demo-project",
            }
        ),
        encoding="utf-8",
    )
    (run2_dir / "reports").mkdir()
    (run2_dir / "reports" / "summary.json").write_text(
        json.dumps(
            {
                "run_id": "20260616_000002",
                "total_samples": 1,
                "metrics": {
                    "DR": 0.95,
                    "CPR": 0.85,
                    "avg_reward": 0.9,
                    "condR": 0.8,
                    "avg_time_ms": 120,
                },
                "failure_breakdown": {"commonsense.math_formula": 1},
            }
        ),
        encoding="utf-8",
    )

    # Run without project
    run3_dir = runs_dir / "20260616_000003"
    run3_dir.mkdir(parents=True)
    (run3_dir / "run_manifest.json").write_text(
        json.dumps(
            {
                "run_id": "20260616_000003",
                "created_at": "2026-06-16T00:00:03Z",
                "mode": "eval_only",
            }
        ),
        encoding="utf-8",
    )
    (run3_dir / "reports").mkdir()
    (run3_dir / "reports" / "summary.json").write_text(
        json.dumps(
            {
                "run_id": "20260616_000003",
                "total_samples": 1,
                "metrics": {"DR": 1.0, "CPR": 1.0, "avg_reward": 1.5},
                "failure_breakdown": {},
            }
        ),
        encoding="utf-8",
    )

    return ws


def test_rebuild_creates_runs_index(sample_workspace):
    stats = rebuild_index(sample_workspace)
    assert stats["run_count"] == 3

    runs_index = json.loads((sample_workspace / "index" / "runs_index.json").read_text())
    assert len(runs_index["runs"]) == 3
    run_ids = [r["run_id"] for r in runs_index["runs"]]
    assert run_ids == sorted(run_ids, reverse=True)

    demo_runs = [r for r in runs_index["runs"] if r.get("project") == "demo-project"]
    assert len(demo_runs) == 2


def test_rebuild_creates_projects_json(sample_workspace):
    stats = rebuild_index(sample_workspace)
    assert stats["project_count"] == 1

    projects_index = json.loads((sample_workspace / "index" / "projects.json").read_text())
    assert len(projects_index["projects"]) == 1
    project = projects_index["projects"][0]
    assert project["id"] == "demo-project"
    assert project["name"] == "Demo Project"
    assert project["run_count"] == 2
    assert project["latest_run_id"] == "20260616_000002"


def test_rebuild_cross_reference_latest_run(sample_workspace):
    rebuild_index(sample_workspace)
    projects_index = json.loads((sample_workspace / "index" / "projects.json").read_text())
    project = projects_index["projects"][0]
    # Latest run is the one with greatest run_id
    assert project["latest_run_id"] == "20260616_000002"


def test_rebuild_empty_workspace(tmp_path):
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "index").mkdir()
    stats = rebuild_index(ws)
    assert stats["run_count"] == 0
    assert stats["project_count"] == 0

    runs_index = json.loads((ws / "index" / "runs_index.json").read_text())
    projects_index = json.loads((ws / "index" / "projects.json").read_text())
    assert runs_index["runs"] == []
    assert projects_index["projects"] == []


def test_rebuild_ignores_missing_summary(tmp_path):
    ws = tmp_path / "workspace"
    run_dir = ws / "runs" / "20260616_000001"
    run_dir.mkdir(parents=True)
    (run_dir / "run_manifest.json").write_text(
        json.dumps({"run_id": "20260616_000001"}), encoding="utf-8"
    )
    # No summary.json
    stats = rebuild_index(ws)
    assert stats["run_count"] == 0
