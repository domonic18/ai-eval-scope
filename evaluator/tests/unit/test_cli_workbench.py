"""CLI 工作台命令单测 — runs / doctor / scenario show / session（Sprint 10）。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

from agent_eval.cli.cmds import doctor, runs
from agent_eval.cli.cmds.scenario import scenario_app

runner = CliRunner()


# ── runs ───────────────────────────────────────────────────────────────


def _make_run(ws: Path, run_id: str, *, reward: float = 0.78, mode: str = "pipeline") -> Path:
    run_dir = ws / "runs" / run_id
    (run_dir / "reports").mkdir(parents=True)
    (run_dir / "run_manifest.json").write_text(
        json.dumps({"mode": mode, "package_ref": "chat@1.0.0", "sut": {"name": "sasan"}}),
        encoding="utf-8",
    )
    (run_dir / "reports" / "summary.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "total_samples": 15,
                "metrics": {"chat:reward": reward, "chat:delivery_rate": 0.93},
                "metric_definitions": [
                    {"id": "chat:reward", "name": "Reward", "threshold": 0.75},
                    {"id": "chat:delivery_rate", "name": "交付率", "threshold": 0.95},
                ],
                "failure_breakdown": {"safety.compliance": 2},
            }
        ),
        encoding="utf-8",
    )
    return run_dir


class TestRuns:
    def test_scan_and_list(self, tmp_path: Path) -> None:
        _make_run(tmp_path, "20260831_093012")
        _make_run(tmp_path, "20260830_154501", reward=0.75, mode="run")
        scanned = runs.scan_runs(tmp_path)
        assert [r["run_id"] for r in scanned] == ["20260831_093012", "20260830_154501"]  # 新→旧
        assert scanned[0]["reward"] == "0.78"
        assert scanned[1]["mode"] == "run"

    def test_scan_empty_workspace(self, tmp_path: Path) -> None:
        assert runs.scan_runs(tmp_path) == []

    def test_show_run_renders_metrics_and_breakdown(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _make_run(tmp_path, "20260831_093012")
        monkeypatch.setenv("WORKSPACE_DIR", str(tmp_path))
        result = runner.invoke(runs.runs_app, ["show", "20260831_093012"])
        assert result.exit_code == 0, result.output
        assert "Reward" in result.output and "0.780" in result.output
        assert "safety.compliance" in result.output

    def test_show_run_missing_exits_1(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("WORKSPACE_DIR", str(tmp_path))
        result = runner.invoke(runs.runs_app, ["show", "nope"])
        assert result.exit_code == 1
        assert "不存在" in result.output

    def test_show_run_json_mode(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from agent_eval.cli.console import output

        _make_run(tmp_path, "20260831_093012")
        monkeypatch.setenv("WORKSPACE_DIR", str(tmp_path))
        output.set_output_format("json")
        try:
            result = runner.invoke(runs.runs_app, ["show", "20260831_093012"])
        finally:
            output.set_output_format("text")
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["run_id"] == "20260831_093012"
        assert payload["summary"]["metrics"]["chat:reward"] == 0.78


# ── doctor ─────────────────────────────────────────────────────────────


class TestDoctor:
    def test_checks_structure(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("WORKSPACE_DIR", str(tmp_path))
        monkeypatch.delenv("AGENT_EVAL_HOST", raising=False)
        monkeypatch.delenv("AGENT_EVAL_API_KEY", raising=False)
        checks = {c["name"]: c for c in doctor.run_checks()}
        assert set(checks) == {"平台", "模型", "凭证", "场景包", "workspace", "依赖 extras"}
        assert checks["平台"]["status"] == "warn"
        assert checks["模型"]["status"] in ("ok", "err")  # 取决于本机 llm.json
        assert checks["场景包"]["status"] == "ok"  # 内置包随 wheel 发布

    def test_has_blocking_only_on_models_err(self) -> None:
        assert doctor.has_blocking([{"name": "模型", "status": "err"}]) is True
        assert doctor.has_blocking([{"name": "模型", "status": "ok"}]) is False
        assert doctor.has_blocking([{"name": "平台", "status": "err"}]) is False


# ── scenario show ──────────────────────────────────────────────────────


class TestScenarioShow:
    def test_show_manifest_builtin(self) -> None:
        result = runner.invoke(scenario_app, ["show", "chat", "--section", "manifest"])
        assert result.exit_code == 0, result.output
        assert "chat" in result.output
        assert "default_task_set" in result.output

    def test_show_tree_builtin(self) -> None:
        result = runner.invoke(scenario_app, ["show", "chat"])
        assert result.exit_code == 0, result.output
        assert "agent_eval.yaml" in result.output

    def test_show_rules_builtin(self) -> None:
        result = runner.invoke(scenario_app, ["show", "chat", "--section", "rules"])
        assert result.exit_code == 0, result.output

    def test_show_sut_builtin(self) -> None:
        result = runner.invoke(scenario_app, ["show", "chat", "--section", "sut"])
        assert result.exit_code == 0, result.output
        assert "credential_ref" in result.output or "sut_configs" in result.output

    def test_show_unknown_section_exits_2(self) -> None:
        result = runner.invoke(scenario_app, ["show", "chat", "--section", "nope"])
        assert result.exit_code == 2

    def test_show_by_path(self, tmp_path: Path) -> None:
        (tmp_path / "rules").mkdir()
        (tmp_path / "agent_eval.yaml").write_text(
            "package:\n  id: p\n  scenario: s\n  version: 0.1.0\n", encoding="utf-8"
        )
        result = runner.invoke(scenario_app, ["show", str(tmp_path), "--section", "manifest"])
        assert result.exit_code == 0, result.output

    def test_new_rejects_unimplemented_mode(self, tmp_path: Path) -> None:
        result = runner.invoke(
            scenario_app, ["new", "x/y", "--mode", "agent", "--output", str(tmp_path / "p")]
        )
        assert result.exit_code == 1
        assert "Sprint 11" in result.output


# ── workbench session ──────────────────────────────────────────────────


class TestSession:
    def test_context_refresh_and_banner(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from agent_eval.cli.workbench.session import WorkbenchSession

        monkeypatch.delenv("AGENT_EVAL_HOST", raising=False)
        monkeypatch.delenv("AGENT_EVAL_API_KEY", raising=False)
        s = WorkbenchSession()
        assert s.ctx.platform_ok is False
        assert "评测工作台" in s.ctx.banner()

    def test_unknown_domain_exits_2(self) -> None:
        from agent_eval.cli.main import app
        from agent_eval.cli.workbench.session import WorkbenchSession

        with pytest.raises(typer.Exit) as ei:
            WorkbenchSession().run("nope")
        assert ei.value.exit_code == 2
        # start 命令入口可被 invoke（域直达失败路径）
        result = runner.invoke(app, ["start", "--domain", "nope"])
        assert result.exit_code == 2
