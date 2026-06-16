"""Tests for CLI `agent-eval index` command."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from cli import app

runner = CliRunner()


def test_index_command_rebuilds(tmp_path, monkeypatch):
    """index command calls rebuild_index and prints stats."""
    from agent_eval.web import indexer

    captured = {}

    def fake_rebuild_index(workspace_dir: Path):
        captured["workspace"] = str(workspace_dir)
        return {"project_count": 2, "run_count": 5}

    monkeypatch.setattr(indexer, "rebuild_index", fake_rebuild_index)

    result = runner.invoke(app, ["index", "--workspace", str(tmp_path)])
    assert result.exit_code == 0
    assert "索引重建完成" in result.output
    assert "项目数: 2" in result.output
    assert "运行数: 5" in result.output
    assert captured["workspace"] == str(tmp_path.resolve())


def test_index_command_failure(tmp_path, monkeypatch):
    """index command reports errors gracefully."""
    from agent_eval.web import indexer

    def fake_rebuild_index(workspace_dir: Path):
        raise RuntimeError("disk full")

    monkeypatch.setattr(indexer, "rebuild_index", fake_rebuild_index)

    result = runner.invoke(app, ["index", "--workspace", str(tmp_path)])
    assert result.exit_code == 1
    assert "索引重建失败" in result.output
    assert "disk full" in result.output
