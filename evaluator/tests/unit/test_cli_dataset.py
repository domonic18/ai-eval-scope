"""CLI `agent-eval dataset download` 命令测试。"""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from agent_eval.cli import app

runner = CliRunner()


def test_dataset_download_help() -> None:
    result = runner.invoke(app, ["dataset", "download", "--help"])
    assert result.exit_code == 0
    assert "下载源" in result.output


def test_dataset_download_success(tmp_path: Path, monkeypatch) -> None:
    captured: dict = {}

    def fake_download(self, name, **kwargs):  # type: ignore[no-untyped-def]
        captured["name"] = name
        target = tmp_path / name
        target.mkdir(parents=True)
        return target

    monkeypatch.setattr("agent_eval.datasets.DatasetManager.download", fake_download)

    result = runner.invoke(app, ["dataset", "download", "ceval", "-o", str(tmp_path)])
    assert result.exit_code == 0
    assert captured["name"] == "ceval"
    assert "✅" in result.output


def test_dataset_download_failure_exit_code(monkeypatch) -> None:
    from agent_eval.core.exceptions import DatasetError

    def fake_download(self, name, **kwargs):  # type: ignore[no-untyped-def]
        raise DatasetError("boom")

    monkeypatch.setattr("agent_eval.datasets.DatasetManager.download", fake_download)

    result = runner.invoke(app, ["dataset", "download", "ceval"])
    assert result.exit_code == 1
    assert "❌" in result.output


def test_dataset_subcommand_registered() -> None:
    """`agent-eval --help` 应列出 dataset 子命令组。"""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "dataset" in result.output
