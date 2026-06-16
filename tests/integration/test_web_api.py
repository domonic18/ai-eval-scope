"""Integration tests for Web Portal Express API."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest
import requests


@pytest.fixture(scope="module")
def backend_dir():
    """Return absolute path to web/backend."""
    return Path(__file__).resolve().parents[2] / "web" / "backend"


@pytest.fixture(scope="module")
def node_modules_ready(backend_dir):
    """Ensure backend node_modules exists; skip otherwise."""
    if not shutil.which("node"):
        pytest.skip("Node.js not installed")
    nm = backend_dir / "node_modules"
    if not nm.exists():
        # Try to install dependencies once
        subprocess.run(
            ["npm", "install"],
            cwd=backend_dir,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    if not nm.exists():
        pytest.skip("Backend node_modules not available")
    return True


@pytest.fixture
def test_server(tmp_path, backend_dir, node_modules_ready):
    """Start Express backend with a temporary workspace."""
    ws = tmp_path / "workspace"
    index_dir = ws / "index"
    runs_dir = ws / "runs"
    index_dir.mkdir(parents=True)
    runs_dir.mkdir(parents=True)

    # Create a sample run
    run_dir = runs_dir / "20260616_120000"
    run_dir.mkdir(parents=True)
    (run_dir / "run_manifest.json").write_text(
        json.dumps(
            {
                "run_id": "20260616_120000",
                "created_at": "2026-06-16T12:00:00Z",
                "mode": "eval_only",
                "project": "demo-project",
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "reports").mkdir()
    (run_dir / "reports" / "summary.json").write_text(
        json.dumps(
            {
                "run_id": "20260616_120000",
                "total_samples": 1,
                "metrics": {"DR": 1.0, "CPR": 0.9, "avg_reward": 1.2},
                "failure_breakdown": {},
                "sample_scores": [],
            }
        ),
        encoding="utf-8",
    )
    results_dir = run_dir / "results" / "task_001"
    results_dir.mkdir(parents=True)
    (results_dir / "rule_results.json").write_text(
        json.dumps(
            [
                {
                    "rule_id": "format.response_format",
                    "constraint_id": "format.response_format",
                    "name": "文件格式检查",
                    "tier": "hard_gate",
                    "passed": True,
                    "score": 1.0,
                    "reason": "格式正确",
                    "duration_ms": 10,
                    "judge_provider": None,
                    "judge_model": None,
                }
            ]
        ),
        encoding="utf-8",
    )
    (results_dir / "scores.json").write_text(
        json.dumps(
            {
                "s_format": 1.0,
                "s_common": 0.0,
                "s_soft": 0.0,
                "s_pref": 0.0,
                "reward": 1.0,
            }
        ),
        encoding="utf-8",
    )
    (results_dir / "report.json").write_text(
        json.dumps({"sample_id": "task_001"}), encoding="utf-8"
    )
    (results_dir / "evidence").mkdir()
    (results_dir / "evidence" / "judge.json").write_text(
        json.dumps({"provider": "test"}), encoding="utf-8"
    )

    # Seed projects.json and runs_index.json
    index_dir.mkdir(parents=True, exist_ok=True)
    (index_dir / "projects.json").write_text(
        json.dumps(
            {
                "projects": [
                    {
                        "id": "demo-project",
                        "name": "Demo Project",
                        "description": "",
                        "run_count": 1,
                        "latest_run_id": "20260616_120000",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (index_dir / "runs_index.json").write_text(
        json.dumps(
            {
                "runs": [
                    {
                        "run_id": "20260616_120000",
                        "mode": "eval_only",
                        "total_samples": 1,
                        "metrics": {"DR": 1.0, "CPR": 0.9, "avg_reward": 1.2},
                        "failure_breakdown": {},
                        "created_at": "2026-06-16T12:00:00Z",
                        "project": "demo-project",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    env = os.environ.copy()
    env["WORKSPACE_DIR"] = str(ws)
    env["PORT"] = "0"  # Let OS choose port; we parse from stdout
    env["HOST"] = "127.0.0.1"

    proc = subprocess.Popen(
        ["node", "server.js"],
        cwd=backend_dir,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    # Wait for server to start and parse port
    port = None
    start = time.time()
    while time.time() - start < 10:
        line = proc.stdout.readline()
        if line:
            # e.g. "Agent Eval Web Portal running at http://127.0.0.1:53123"
            if "http://" in line:
                port = int(line.strip().rsplit(":", 1)[-1])
                break
        if proc.poll() is not None:
            break
        time.sleep(0.05)

    if port is None:
        proc.terminate()
        pytest.skip("Failed to start test server")

    base_url = f"http://127.0.0.1:{port}"
    yield base_url

    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


def test_health(test_server):
    resp = requests.get(f"{test_server}/api/health", timeout=5)
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_get_projects(test_server):
    resp = requests.get(f"{test_server}/api/projects", timeout=5)
    assert resp.status_code == 200
    data = resp.json()
    assert "projects" in data
    assert len(data["projects"]) == 1
    assert data["projects"][0]["id"] == "demo-project"


def test_get_project(test_server):
    resp = requests.get(f"{test_server}/api/projects/demo-project", timeout=5)
    assert resp.status_code == 200
    assert resp.json()["id"] == "demo-project"


def test_get_project_runs(test_server):
    resp = requests.get(f"{test_server}/api/projects/demo-project/runs", timeout=5)
    assert resp.status_code == 200
    assert len(resp.json()["runs"]) == 1


def test_get_project_trends(test_server):
    resp = requests.get(f"{test_server}/api/projects/demo-project/trends", timeout=5)
    assert resp.status_code == 200
    data = resp.json()
    assert data["project_id"] == "demo-project"
    assert len(data["data_points"]) == 1


def test_get_run(test_server):
    resp = requests.get(f"{test_server}/api/runs/20260616_120000", timeout=5)
    assert resp.status_code == 200
    assert resp.json()["run_id"] == "20260616_120000"


def test_get_run_tasks(test_server):
    resp = requests.get(f"{test_server}/api/runs/20260616_120000/tasks", timeout=5)
    assert resp.status_code == 200
    assert resp.json()["tasks"] == ["task_001"]


def test_get_task_detail(test_server):
    resp = requests.get(f"{test_server}/api/runs/20260616_120000/tasks/task_001", timeout=5)
    assert resp.status_code == 200
    data = resp.json()
    assert data["task_id"] == "task_001"
    assert len(data["rule_results"]) == 1
    assert data["evidence_files"] == ["judge.json"]


def test_get_evidence_file(test_server):
    resp = requests.get(
        f"{test_server}/api/runs/20260616_120000/tasks/task_001/evidence/judge.json",
        timeout=5,
    )
    assert resp.status_code == 200
    assert resp.json()["provider"] == "test"


def test_rebuild_index_endpoint(test_server, tmp_path):
    resp = requests.post(f"{test_server}/api/index/rebuild", timeout=5)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["run_count"] == 1
    assert data["project_count"] == 0  # no assets/projects in tmp workspace


def test_spa_fallback(test_server, backend_dir):
    resp = requests.get(f"{test_server}/nonexistent", timeout=5)
    public_dir = backend_dir / "public"
    if public_dir.exists() and (public_dir / "index.html").exists():
        # SPA fallback serves index.html
        assert resp.status_code == 200
        assert '<div id="root">' in resp.text
    else:
        assert resp.status_code == 404
