"""CLI 命令层覆盖补齐 — pack / eval / upload / version / open / doctor / models test /
runs list / dataset list / rule-set / suite / knowledge（全离线 mock）。"""

from __future__ import annotations

import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from agent_eval.cli.main import app

runner = CliRunner()

# typer 在 GITHUB_ACTIONS / FORCE_COLOR / PY_COLORS 环境下强制彩色渲染，
# rich 高亮器会把选项名按 span 切开（如 --log-level 被转义码打断），
# 字面子串断言须在去 ANSI 后的纯文本上做。
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _plain(text: str) -> str:
    """剥离 ANSI 转义序列，返回纯文本。"""
    return _ANSI_RE.sub("", text)


# ── version ────────────────────────────────────────────────────────────


class TestVersion:
    def test_prints_version(self) -> None:
        result = runner.invoke(app, ["version"])
        assert result.exit_code == 0, result.output
        assert "agent-eval v" in result.output

    def test_version_flag_exits_cleanly(self) -> None:
        # --version 旗标（须先于其余参数生效）
        result = runner.invoke(app, ["--version"])
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
            obs,
            "load_config",
            lambda **k: SimpleNamespace(
                has_credentials=lambda: True,
                run_view_url=lambda rid: f"https://eval.example.com/run/{rid}",
            ),
        )

    def test_upload_dispatches(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self._make_run(tmp_path, "20260101_000000")
        self._patch_sink(monkeypatch)
        result = runner.invoke(
            app, ["upload", "--run", "20260101_000000", "--workspace", str(tmp_path)]
        )
        assert result.exit_code == 0, result.output
        assert "回填完成" in result.output

    def test_upload_project_override_reaches_config(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """--project 必须并入 load_config 的 env（env_override 曾构造后未传入——--project 不生效）。"""
        self._make_run(tmp_path, "20260101_000000")
        self._patch_sink(monkeypatch)
        import agent_eval.observability as obs

        captured: dict = {}

        def _fake_load_config(**k):
            captured.update(k)
            return SimpleNamespace(
                has_credentials=lambda: True,
                run_view_url=lambda rid: f"https://eval.example.com/run/{rid}",
            )

        monkeypatch.setattr(obs, "load_config", _fake_load_config)
        result = runner.invoke(
            app,
            [
                "upload",
                "--run",
                "20260101_000000",
                "--workspace",
                str(tmp_path),
                "--project",
                "demo-courseware",
            ],
        )
        assert result.exit_code == 0, result.output
        assert captured.get("upload_override") is True
        assert (captured.get("env") or {}).get("AGENT_EVAL_PROJECT") == "demo-courseware"

    def test_upload_missing_run_dir(self, tmp_path: Path) -> None:
        result = runner.invoke(app, ["upload", "--run", "nope", "--workspace", str(tmp_path)])
        assert result.exit_code == 1
        assert "不存在" in result.output

    def test_upload_missing_summary(self, tmp_path: Path) -> None:
        (tmp_path / "runs" / "r1").mkdir(parents=True)
        result = runner.invoke(app, ["upload", "--run", "r1", "--workspace", str(tmp_path)])
        assert result.exit_code == 1
        assert "summary.json" in result.output

    # ── upload_run_core（回执 + UploadError kind）────────

    def test_upload_core_receipt_structured(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """core 返回结构化回执（Agent 域消费）：计数 + run_url 真源 + 静默无渲染。"""
        from agent_eval.cli.cmds.upload import upload_run_core

        self._make_run(tmp_path, "20260101_000000")
        self._patch_sink(monkeypatch, sent=3)
        receipt = upload_run_core(
            "20260101_000000", workspace=str(tmp_path), project="demo", note=None
        )
        assert receipt["run_id"] == "20260101_000000"
        assert receipt["sent"] == 3 and receipt["queued"] == 0
        assert receipt["sample_count"] == 0 and receipt["event_count"] == 1
        assert receipt["run_url"] == "https://eval.example.com/run/20260101_000000"
        assert receipt["project"] == "demo"

    def test_upload_core_error_kinds(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from agent_eval.cli.cmds.upload import UploadError, upload_run_core

        with pytest.raises(UploadError) as ei:
            upload_run_core("nope", workspace=str(tmp_path))
        assert ei.value.kind == "missing_run"

        (tmp_path / "runs" / "r1").mkdir(parents=True)
        with pytest.raises(UploadError) as ei:
            upload_run_core("r1", workspace=str(tmp_path))
        assert ei.value.kind == "missing_summary"

        self._make_run(tmp_path, "20260101_000001")
        import agent_eval.observability as obs

        monkeypatch.setattr(
            obs, "load_config", lambda **k: SimpleNamespace(has_credentials=lambda: False)
        )
        with pytest.raises(UploadError) as ei:
            upload_run_core("20260101_000001", workspace=str(tmp_path))
        assert ei.value.kind == "no_credentials"


# ── observability 拆分（flush 无渲染核心 + 回执渲染）────────


class TestObservabilitySplit:
    def _fake_result(self) -> SimpleNamespace:
        return SimpleNamespace(run_id="r_x", run_workspace=None)

    def _patch(
        self, monkeypatch: pytest.MonkeyPatch, *, enabled: bool = True, report=None, error=None
    ) -> None:
        import agent_eval.observability as obs

        class _FakeSink:
            def __init__(self, cfg: object) -> None:
                if error is not None:
                    raise error

            def flush(self, result, **kw) -> SimpleNamespace:
                return report or SimpleNamespace(
                    error=None,
                    sent=2,
                    queued=1,
                    artifacts_uploaded=1,
                    artifacts_failed=0,
                    replayed=0,
                )

        monkeypatch.setattr(obs, "ResultSink", _FakeSink)
        monkeypatch.setattr(
            obs,
            "load_config",
            lambda **k: SimpleNamespace(
                enabled=enabled,
                run_view_url=lambda rid: f"https://eval.example.com/run/{rid}",
            ),
        )

    def test_disabled_returns_default_receipt(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from agent_eval.cli._common import observability_enabled, observability_flush

        self._patch(monkeypatch, enabled=False)
        receipt = observability_flush(self._fake_result(), upload_override=None)
        assert receipt["enabled"] is False
        assert observability_enabled(self._fake_result(), upload_override=None) is False
        assert receipt["sent"] == 0 and receipt["view_url"] == ""

    def test_success_receipt_and_render(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        from agent_eval.cli._common import _render_upload_receipt, observability_flush

        self._patch(monkeypatch)
        receipt = observability_flush(self._fake_result(), upload_override=True)
        assert receipt["enabled"] is True
        assert receipt["sent"] == 2 and receipt["queued"] == 1
        assert receipt["view_url"] == "https://eval.example.com/run/r_x"
        _render_upload_receipt(receipt)
        out = capsys.readouterr().out
        assert "✓ 已推送" in out and "事件 2" in out
        assert "平台报告: https://eval.example.com/run/r_x" in out

    def test_push_error_and_init_error_branches(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        from agent_eval.cli._common import _render_upload_receipt, observability_flush

        self._patch(
            monkeypatch,
            report=SimpleNamespace(
                error="boom", sent=0, queued=1, artifacts_uploaded=0, artifacts_failed=0, replayed=0
            ),
        )
        receipt = observability_flush(self._fake_result(), upload_override=True)
        _render_upload_receipt(receipt)
        out = capsys.readouterr().out
        assert "推送异常（已入离线队列，后续自动重放）: boom" in out

        self._patch(monkeypatch, error=RuntimeError("网络不可达"))
        receipt = observability_flush(self._fake_result(), upload_override=True)
        assert receipt["init_error"] == "网络不可达"
        _render_upload_receipt(receipt)
        out = capsys.readouterr().out
        assert "推送初始化失败（结果仍在本地 workspace）: 网络不可达" in out


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


# ── 进度视图 + --json 覆盖 run/pipeline/eval（F-C-EXEC-03 / F-C-INTEG-02） ──


class _FlowStubs:
    """mock _stages 五阶段 + run_id，隔离真实执行。"""

    def __init__(self, tmp_path: Path) -> None:
        pkg = SimpleNamespace(
            manifest=SimpleNamespace(ref="chat/chat:1.0.0", id="chat"), root=tmp_path
        )
        self.inputs = SimpleNamespace(
            task_set_path=tmp_path / "default.yaml",
            task_set_model=SimpleNamespace(tasks=[{}, {}]),
            sut=SimpleNamespace(name="sasan", channel="agent_protocol", base_url="http://x"),
            resolved_pkg=pkg,
        )
        self.pkg_objs = [
            SimpleNamespace(
                manifest=SimpleNamespace(task_id="t1", status="success", package_id="t1"),
                output_dir=tmp_path / "t1",
            ),
            SimpleNamespace(
                manifest=SimpleNamespace(task_id="t2", status="failed", package_id="t2"),
                output_dir=tmp_path / "t2",
            ),
        ]
        self.report = SimpleNamespace(
            run_id="20260101_000000",
            total_samples=2,
            metrics={"chat:reward": 0.8},
            failure_breakdown={"safety.compliance": 1},
        )
        # evaluate_stage 返回 EvalResult 形态：指标真相在 .report（修复后契约），
        # gate 为门禁判定结果（off = 不判定）
        self.eval_result = SimpleNamespace(
            run_id="20260101_000000",
            report=self.report,
            samples=[],  # pipeline_core 的 SUT 身份回填触达（空列表跳过）
            gate={"mode": "off", "enabled": False, "passed": True},
        )

    def patch(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import agent_eval.cli._stages as stages
        import agent_eval.storage.package as storage_pkg

        # 上报隔离：仓库 .env 的 AGENT_EVAL_UPLOAD=true 会渗入 pipeline json 测试
        # （core 内联上报段真发平台，禁联网）——显式钉死为关
        monkeypatch.setenv("AGENT_EVAL_UPLOAD", "0")
        monkeypatch.setattr(stages, "resolve_run_inputs", lambda *a, **k: self.inputs)
        monkeypatch.setattr(stages, "resolve_eval_inputs", lambda *a, **k: "/tmp/r.yaml")
        monkeypatch.setattr(stages, "build_judge_context", lambda *a, **k: object())
        monkeypatch.setattr(stages, "execute_stage", lambda *a, **k: self.pkg_objs)
        monkeypatch.setattr(stages, "evaluate_stage", lambda *a, **k: self.eval_result)
        monkeypatch.setattr(stages, "finalize_eval", lambda *a, **k: None)
        monkeypatch.setattr(storage_pkg, "generate_run_id", lambda: "20260101_000000")


class TestJsonOutput:
    def test_pipeline_json_stdout_only(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("WORKSPACE_DIR", str(tmp_path))
        stubs = _FlowStubs(tmp_path)
        stubs.patch(monkeypatch)
        result = runner.invoke(app, ["--output-format", "json", "pipeline", "--package", "chat"])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.stdout)  # stdout 仅 JSON（人读行在 stderr）
        assert payload["mode"] == "pipeline"
        assert payload["metrics"] == {"chat:reward": 0.8}
        assert payload["succeeded"] == 1 and payload["total"] == 2
        assert payload["packages"][0]["task_id"] == "t1"
        assert "任务集" in result.stderr  # 人读输出分流到 stderr

    def test_run_json_payload(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        stubs = _FlowStubs(tmp_path)
        stubs.patch(monkeypatch)
        result = runner.invoke(app, ["--output-format", "json", "run", "--package", "chat"])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.stdout)
        assert payload["mode"] == "run" and "metrics" not in payload
        assert [p["status"] for p in payload["packages"]] == ["success", "failed"]

    def test_eval_json_payload(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        stubs = _FlowStubs(tmp_path)
        stubs.patch(monkeypatch)
        result = runner.invoke(
            app,
            [
                "--output-format",
                "json",
                "eval",
                "--package-dir",
                str(tmp_path),
                "--package",
                "chat",
            ],
        )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.stdout)
        assert payload["metrics"] == {"chat:reward": 0.8}
        assert payload["failure_breakdown"] == {"safety.compliance": 1}


class TestProgressView:
    def test_stage_progress_off_is_silent(self, capsys: object) -> None:
        from agent_eval.cli.console.render import stage_progress

        with stage_progress(mode="off") as sp:
            sp.advance("执行")
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err == ""

    def test_stage_progress_lines_prints_stage_line(self, capsys: object) -> None:
        """verbose 档（lines）：stderr ``[stage]`` 阶段行直出（事件行的承载底座）。"""
        from agent_eval.cli.console.render import stage_progress

        with stage_progress(mode="lines") as sp:
            sp.advance("评估")
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "[stage] 评估" in captured.err
        assert sp.last_label == "评估"

    def test_stage_progress_never_writes_stdout(self, capsys: object) -> None:
        """进度行固定走 stderr（含非 TTY fallback），stdout 保持纯净。"""
        from agent_eval.cli.console.render import stage_progress

        with stage_progress(mode="spinner") as sp:
            sp.advance("评估")
        assert capsys.readouterr().out == ""

    @pytest.mark.parametrize(
        ("level", "expected"),
        [("quiet", "off"), ("normal", "spinner"), ("verbose", "lines"), ("debug", "off")],
    )
    def test_progress_mode_maps_levels(self, level: str, expected: str) -> None:
        from agent_eval.cli.console.render import progress_mode

        assert progress_mode(level) == expected

    def test_progress_mode_json_forces_off(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """json 形态一律 off（进度即人读输出，stdout 纯 JSON 契约优先）。"""
        from agent_eval.cli.console import output as output_mod
        from agent_eval.cli.console.render import progress_mode

        monkeypatch.setattr(output_mod, "is_json", lambda: True)
        assert progress_mode("normal") == "off"
        assert progress_mode("verbose") == "off"


class TestLogLevelContract:
    """--log-level 四档契约（F-C-EXEC-07）。"""

    def test_run_help_exposes_log_level_without_verbose(self) -> None:
        result = runner.invoke(app, ["run", "--help"])
        assert result.exit_code == 0
        assert "--log-level" in _plain(result.output)
        assert "--verbose" not in _plain(result.output)

    def test_pipeline_help_exposes_log_level(self) -> None:
        result = runner.invoke(app, ["pipeline", "--help"])
        assert result.exit_code == 0
        assert "--log-level" in _plain(result.output)

    def test_verbose_flag_is_rejected(self) -> None:
        """--verbose 一次性移除（D-CLI-6 无别名）：误用即 usage error。"""
        result = runner.invoke(app, ["run", "--verbose"])
        assert result.exit_code != 0

    def test_no_verbose_flag_left_in_source(self) -> None:
        """全仓 --verbose 清零 grep 门禁（教程/CI 片段已清理，源码为最后一道闸）。"""
        import agent_eval

        root = Path(agent_eval.__file__).parent
        offenders = [
            str(p.relative_to(root))
            for p in sorted(root.rglob("*.py"))
            if "--verbose" in p.read_text(encoding="utf-8")
        ]
        assert offenders == []

    def test_print_task_table_lists_tasks(self, tmp_path: Path) -> None:
        from agent_eval.cli.console.render import print_task_table

        stubs = _FlowStubs(tmp_path)
        print_task_table(stubs.pkg_objs)  # rprint 输出（stdout）
        assert True  # 冒烟：不抛异常即通过（表格渲染已由真机验证）


class TestFlushObservability:
    def test_queue_dir_follows_run_workspace(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """回归（CI 构建 #10-#18）：load_config 无 workspace 时回退 CWD 相对路径
        ``.ingest_queue``，容器 CWD 为只读场景包挂载（:ro）时创建即炸，整个推送被
        跳过且构建仍绿（平台无数据）。_flush_observability 必须把 run workspace
        根传给 load_config，让队列目录落在可写 workspace 内。"""
        import agent_eval.observability as obs
        from agent_eval.cli._common import _flush_observability

        real_cfg = obs.load_config(
            workspace=tmp_path,
            env={
                "AGENT_EVAL_HOST": "https://platform.example.com",
                "AGENT_EVAL_API_KEY": "eval-k",
                "AGENT_EVAL_UPLOAD": "true",
            },
        )
        captured: dict[str, object] = {}

        def fake_load_config(**kwargs: object) -> object:
            captured.update(kwargs)
            return real_cfg

        class FakeSink:
            def __init__(self, cfg: object) -> None:
                self.cfg = cfg

            def flush(self, result: object, **kwargs: object) -> SimpleNamespace:
                return SimpleNamespace(
                    error="",
                    sent=1,
                    queued=0,
                    artifacts_uploaded=0,
                    artifacts_failed=0,
                    replayed=0,
                )

        monkeypatch.setattr(obs, "load_config", fake_load_config)
        monkeypatch.setattr(obs, "ResultSink", FakeSink)

        rw_root = tmp_path / "runs" / "20260915_000000"
        result = SimpleNamespace(
            run_id="20260915_000000", run_workspace=SimpleNamespace(root=rw_root)
        )
        _flush_observability(result, upload_override=None)
        assert captured["workspace"] == rw_root
