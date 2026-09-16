"""_detect_run_mode 测试 — run 产物评估上报 agent 模式（修平台「仅评估」误标）。"""

from __future__ import annotations

import json
from pathlib import Path

from agent_eval.cli.cmds.evaluate import _detect_run_mode


def _make_run(tmp_path: Path, mode: str | None) -> Path:
    """构造 runs/{id}/packages/{task} 目录，可选写 run_manifest.json。"""
    run_dir = tmp_path / "runs" / "20260826_000000" / "runs" / "r1"
    run_dir.mkdir(parents=True)
    if mode is not None:
        (run_dir / "run_manifest.json").write_text(
            json.dumps({"mode": mode, "run_id": "r1"}), encoding="utf-8"
        )
    packages = run_dir / "packages"
    (packages / "task_001").mkdir(parents=True)
    return packages


class TestDetectRunMode:
    def test_run_manifest_mode_run_returns_agent(self, tmp_path: Path) -> None:
        packages = _make_run(tmp_path, "run")
        # 包集合目录（runs/{id}/packages）
        assert _detect_run_mode(packages) == "agent"
        # 单包目录（runs/{id}/packages/{task}）
        assert _detect_run_mode(packages / "task_001") == "agent"

    def test_other_manifest_mode_returns_eval_only(self, tmp_path: Path) -> None:
        assert _detect_run_mode(_make_run(tmp_path, "eval_only")) == "eval_only"

    def test_pipeline_manifest_mode_returns_pipeline(self, tmp_path: Path) -> None:
        # pipeline 一体化产物复评时保持 pipeline 语义（Sprint 9）
        assert _detect_run_mode(_make_run(tmp_path, "pipeline")) == "pipeline"

    def test_no_manifest_returns_eval_only(self, tmp_path: Path) -> None:
        assert _detect_run_mode(_make_run(tmp_path, None)) == "eval_only"

    def test_standalone_package_dir_returns_eval_only(self, tmp_path: Path) -> None:
        pkg = tmp_path / "some_package"
        pkg.mkdir()
        assert _detect_run_mode(pkg) == "eval_only"

    def test_corrupt_manifest_falls_back(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "runs" / "r1"
        (run_dir / "packages" / "t").mkdir(parents=True)
        (run_dir / "run_manifest.json").write_text("{not json", encoding="utf-8")
        assert _detect_run_mode(run_dir / "packages") == "eval_only"
