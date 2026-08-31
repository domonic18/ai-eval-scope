"""CLI 命令层覆盖补齐 — pack / eval / upload / version / open / doctor / models test /
runs list / dataset list / rule-set / suite / knowledge（全离线 mock）。"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from agent_eval.cli.main import app

runner = CliRunner()


# ── version ────────────────────────────────────────────────────────────


class TestVersion:
    def test_prints_version(self) -> None:
        result = runner.invoke(app, ["version"])
        assert result.exit_code == 0, result.output
        assert "agent-eval v" in result.output


# ── pack ───────────────────────────────────────────────────────────────


class TestPack:
    def test_pack_files(self, tmp_path: Path) -> None:
        f1 = tmp_path / "a.md"
        f2 = tmp_path / "b.html"
        f1.write_text("# a", encoding="utf-8")
        f2.write_text("<html><body>b</body></html>", encoding="utf-8")
        out = tmp_path / "pkgs"
        result = runner.invoke(
            app,
            [
                "pack",
                "--files",
                str(f1),
                "--files",
                str(f2),
                "--task-id",
                "t1",
                "--output-dir",
                str(out),
            ],
        )
        assert result.exit_code == 0, result.output
        assert (out / "t1" / "manifest.json").exists()

    def test_pack_source_dir(self, tmp_path: Path) -> None:
        src = tmp_path / "docs"
        (src / "sub").mkdir(parents=True)
        (src / "sub" / "x.html").write_text("<html>x</html>", encoding="utf-8")
        out = tmp_path / "pkgs"
        result = runner.invoke(app, ["pack", "--source-dir", str(src), "--output-dir", str(out)])
        assert result.exit_code == 0, result.output
        assert (out / "docs" / "output" / "_manifest.json").exists()  # 目录模式清单

    def test_pack_requires_exactly_one_input(self, tmp_path: Path) -> None:
        assert runner.invoke(app, ["pack"]).exit_code == 1
        f = tmp_path / "a.md"
        f.write_text("x", encoding="utf-8")
        result = runner.invoke(app, ["pack", "--files", str(f), "--source-dir", str(tmp_path)])
        assert result.exit_code == 1
        assert "不能同时指定" in result.output


# ── eval（mock 编排阶段） ──────────────────────────────────────────────


class TestEvalCommand:
    def _patch_stages(self, monkeypatch: pytest.MonkeyPatch, calls: dict) -> None:
        import agent_eval.cli._stages as stages

        monkeypatch.setattr(stages, "resolve_eval_inputs", lambda *a, **k: "/tmp/r.yaml")
        monkeypatch.setattr(stages, "build_judge_context", lambda *a, **k: object())
        monkeypatch.setattr(
            stages,
            "evaluate_stage",
            lambda *a, **k: calls.setdefault("ev", dict(k)) or SimpleNamespace(),
        )
        monkeypatch.setattr(
            stages, "finalize_eval", lambda *a, **k: calls.setdefault("fin", dict(k))
        )

    def test_eval_invokes_stages(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: dict = {}
        self._patch_stages(monkeypatch, calls)
        result = runner.invoke(app, ["eval", "--package-dir", str(tmp_path), "--package", "chat"])
        assert result.exit_code == 0, result.output
        assert "评估模式: pipeline" in result.output
        assert calls["ev"]["project"] is None  # 未传参为真实默认，非 OptionInfo

    def test_eval_agent_mode_rejected(self, tmp_path: Path) -> None:
        result = runner.invoke(
            app, ["eval", "--package-dir", str(tmp_path), "--eval-mode", "agent"]
        )
        assert result.exit_code == 1
        assert "尚未实现" in result.output


# ── upload（mock ResultSink / load_config） ────────────────────────────


class TestUploadCommand:
    def _make_run(self, ws: Path, run_id: str) -> None:
        run_dir = ws / "runs" / run_id / "reports"
        run_dir.mkdir(parents=True)
        (run_dir / "summary.json").write_text(
            json.dumps({"run_id": run_id, "total_samples": 0, "metrics": {}}), encoding="utf-8"
        )

    def _patch_sink(self, monkeypatch: pytest.MonkeyPatch, sent: int = 1) -> None:
        import agent_eval.observability as obs

        class _FakeSink:
            def __init__(self, cfg: object) -> None:
                pass

            def dispatch(self, events: list) -> tuple[int, int]:
                return sent, 0

        monkeypatch.setattr(obs, "ResultSink", _FakeSink)
        monkeypatch.setattr(
            obs, "load_config", lambda **k: SimpleNamespace(has_credentials=lambda: True)
        )

    def test_upload_dispatches(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self._make_run(tmp_path, "20260101_000000")
        self._patch_sink(monkeypatch)
        result = runner.invoke(
            app, ["upload", "--run", "20260101_000000", "--workspace", str(tmp_path)]
        )
        assert result.exit_code == 0, result.output
        assert "回填完成" in result.output

    def test_upload_missing_run_dir(self, tmp_path: Path) -> None:
        result = runner.invoke(app, ["upload", "--run", "nope", "--workspace", str(tmp_path)])
        assert result.exit_code == 1
        assert "不存在" in result.output

    def test_upload_missing_summary(self, tmp_path: Path) -> None:
        (tmp_path / "runs" / "r1").mkdir(parents=True)
        result = runner.invoke(app, ["upload", "--run", "r1", "--workspace", str(tmp_path)])
        assert result.exit_code == 1
        assert "summary.json" in result.output


# ── open ───────────────────────────────────────────────────────────────


class TestOpenCommand:
    def test_open_platform(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import agent_eval.cli.cmds.open_url as ou

        seen: list[str] = []
        monkeypatch.setenv("AGENT_EVAL_HOST", "https://eval.example.com")
        monkeypatch.setattr(ou, "open_url", lambda url: seen.append(url) or True)
        result = runner.invoke(app, ["open", "platform"])
        assert result.exit_code == 0, result.output
        assert seen == ["https://eval.example.com"]

    def test_open_platform_without_host_exits_2(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("AGENT_EVAL_HOST", raising=False)
        result = runner.invoke(app, ["open", "platform"])
        assert result.exit_code == 2

    def test_open_report_local(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import agent_eval.cli.cmds.open_url as ou

        report = tmp_path / "runs" / "r1" / "reports" / "summary.md"
        report.parent.mkdir(parents=True)
        report.write_text("# 报告", encoding="utf-8")
        monkeypatch.setenv("WORKSPACE_DIR", str(tmp_path))
        seen: list[str] = []
        monkeypatch.setattr(ou, "open_path", lambda p: seen.append(p))
        result = runner.invoke(app, ["open", "report", "r1"])
        assert result.exit_code == 0, result.output
        assert seen == [str(report)]

    def test_open_unknown_target_exits_1(self) -> None:
        result = runner.invoke(app, ["open", "nope"])
        assert result.exit_code == 1


# ── doctor 命令层 ──────────────────────────────────────────────────────


class TestDoctorCommand:
    def test_doctor_table(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("WORKSPACE_DIR", str(tmp_path))
        result = runner.invoke(app, ["doctor"])
        assert result.exit_code == 0, result.output
        assert "检查项" in result.output

    def test_doctor_json(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("WORKSPACE_DIR", str(tmp_path))
        result = runner.invoke(app, ["--output-format", "json", "doctor"])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert {c["name"] for c in payload["checks"]} >= {"平台", "模型"}


# ── models test（mock LLMClientFactory） ───────────────────────────────


class TestModelsTestCommand:
    def _save_config(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("AGENT_EVAL_LLM_CONFIG", str(tmp_path / "llm.json"))
        (tmp_path / "llm.json").write_text(
            json.dumps(
                {
                    "version": 1,
                    "default_role": "text",
                    "roles": {
                        "text": {
                            "provider": "deepseek",
                            "model": "m1",
                            "api_key": "sk-x",
                            "base_url": "https://x",
                        }
                    },
                }
            ),
            encoding="utf-8",
        )

    def test_all_roles_ok(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        import agent_eval.llm.factory as factory

        self._save_config(monkeypatch, tmp_path)

        class _Client:
            def chat(self, messages: list) -> object:
                return SimpleNamespace(content="pong")

        monkeypatch.setattr(
            factory, "LLMClientFactory", SimpleNamespace(create=lambda *a, **k: _Client())
        )
        from agent_eval.cli.cmds.models import models_app

        result = runner.invoke(models_app, ["test"])
        assert result.exit_code == 0, result.output
        assert "pong" in result.output

    def test_role_failure_exits_1(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        import agent_eval.llm.factory as factory
        from agent_eval.core.exceptions import LLMNetworkError

        self._save_config(monkeypatch, tmp_path)

        class _Boom:
            def chat(self, messages: list) -> object:
                raise LLMNetworkError("down")

        monkeypatch.setattr(
            factory, "LLMClientFactory", SimpleNamespace(create=lambda *a, **k: _Boom())
        )
        from agent_eval.cli.cmds.models import models_app

        result = runner.invoke(models_app, ["test"])
        assert result.exit_code == 1
        assert "down" in result.output


# ── runs list 命令层 / dataset list ────────────────────────────────────


class TestListCommands:
    def test_runs_list_table(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        run_dir = tmp_path / "runs" / "20260101_000000" / "reports"
        run_dir.mkdir(parents=True)
        (run_dir.parent / "run_manifest.json").write_text(
            json.dumps({"mode": "pipeline", "package_ref": "chat"}), encoding="utf-8"
        )
        (run_dir / "summary.json").write_text(
            json.dumps({"total_samples": 2, "metrics": {"chat:reward": 0.8}}), encoding="utf-8"
        )
        monkeypatch.setenv("WORKSPACE_DIR", str(tmp_path))
        from agent_eval.cli.cmds.runs import runs_app

        result = runner.invoke(runs_app, ["list"])
        assert result.exit_code == 0, result.output
        assert "20260101_000000" in result.output

    def test_dataset_list_reads_index(self) -> None:
        result = runner.invoke(app, ["dataset", "list"])
        assert result.exit_code == 0, result.output
        assert "数据集索引" in result.output


# ── rule-set ───────────────────────────────────────────────────────────


class TestRuleSetCommands:
    def _builtin_rule_set(self) -> Path:
        from agent_eval.packages import PackageManager

        return PackageManager().resolve_ref("courseware").root / "rules" / "coursework-gate.yaml"

    def test_validate_builtin_passes(self) -> None:
        from agent_eval.cli.cmds.rule_set import rule_app

        result = runner.invoke(rule_app, ["validate", "--rule-set", str(self._builtin_rule_set())])
        assert result.exit_code == 0, result.output
        assert "校验通过" in result.output

    def test_validate_missing_file_exits_1(self, tmp_path: Path) -> None:
        from agent_eval.cli.cmds.rule_set import rule_app

        result = runner.invoke(rule_app, ["validate", "--rule-set", str(tmp_path / "nope.yaml")])
        assert result.exit_code == 1

    def test_list_templates_without_templates(self) -> None:
        from agent_eval.cli.cmds.rule_set import rule_app

        result = runner.invoke(
            rule_app, ["list-templates", "--rule-set", str(self._builtin_rule_set())]
        )
        assert result.exit_code == 0, result.output
        assert "未定义模板" in result.output


# ── suite ──────────────────────────────────────────────────────────────


class TestSuiteCommands:
    def _suite_file(self, tmp_path: Path) -> Path:
        f = tmp_path / "suite.yaml"
        f.write_text("suite: smoke\nruns:\n  - { package: chat }\n", encoding="utf-8")
        return f

    def test_plan_expands_matrix(self, tmp_path: Path) -> None:
        from agent_eval.cli.cmds.suite import suite_app

        result = runner.invoke(suite_app, ["plan", "--file", str(self._suite_file(tmp_path))])
        assert result.exit_code == 0, result.output
        assert "chat" in result.output

    def test_run_dry_run(self, tmp_path: Path) -> None:
        from agent_eval.cli.cmds.suite import suite_app

        result = runner.invoke(
            suite_app, ["run", "--file", str(self._suite_file(tmp_path)), "--dry-run"]
        )
        assert result.exit_code == 0, result.output
        assert "0/0" in result.output

    def test_missing_runs_exits_1(self, tmp_path: Path) -> None:
        from agent_eval.cli.cmds.suite import suite_app

        f = tmp_path / "bad.yaml"
        f.write_text("suite: x\n", encoding="utf-8")
        result = runner.invoke(suite_app, ["plan", "--file", str(f)])
        assert result.exit_code == 1
        assert "runs" in result.output


# ── knowledge（convert mock / list 真实 / extract 缺数据源报错） ──────


class TestKnowledgeCommands:
    def test_convert_with_mocked_pipeline(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import agent_eval.knowledge.pipeline as kp

        class _FakePipe:
            def run(self, **kwargs: object) -> str:
                return "/tmp/out.yaml"

        monkeypatch.setattr(kp, "KnowledgePipeline", _FakePipe)
        from agent_eval.cli.cmds.knowledge import knowledge_app

        result = runner.invoke(
            knowledge_app,
            ["convert", "-s", "periodic_table", "-f", "constants", "--subject", "chemistry"],
        )
        assert result.exit_code == 0, result.output
        assert "转换完成" in result.output

    def test_list_subject_fields(self) -> None:
        from agent_eval.cli.cmds.knowledge import knowledge_app

        result = runner.invoke(knowledge_app, ["list", "--subject", "chemistry"])
        assert result.exit_code == 0, result.output
        assert "constants" in result.output

    def test_extract_missing_source_data_exits_1(self, tmp_path: Path) -> None:
        """离线无评测题数据源：走友好报错分支（exit 1），验证绑定与错误链路。"""
        from agent_eval.cli.cmds.knowledge import knowledge_app

        result = runner.invoke(
            knowledge_app,
            [
                "extract",
                "-s",
                "arc",
                "-f",
                "misconceptions",
                "--subject",
                "physics",
                "--data-dir",
                str(tmp_path / "empty"),
            ],
        )
        assert result.exit_code == 1

    def test_merge_dry_run_no_write(self, tmp_path: Path) -> None:
        """merge --dry-run 真实走 merger 但不写盘（离线安全）。"""
        from agent_eval.cli.cmds.knowledge import knowledge_app

        src = tmp_path / "in.yaml"
        src.write_text('constants:\n  - name: 测试常数\n    value: "1.0"\n', encoding="utf-8")
        result = runner.invoke(
            knowledge_app,
            ["merge", "-i", str(src), "--subject", "chemistry", "--dry-run"],
        )
        assert result.exit_code == 0, result.output
        assert "dry-run 未写盘" in result.output

    def test_audit_reports_subject(self) -> None:
        """audit 只读审计内置知识库（离线，默认不写盘）。"""
        from agent_eval.cli.cmds.knowledge import knowledge_app

        result = runner.invoke(knowledge_app, ["audit", "--subject", "chemistry"])
        assert result.exit_code == 0, result.output
        assert "chemistry" in result.output
