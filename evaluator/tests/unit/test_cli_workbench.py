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

    def test_scan_status_and_error_from_agent_logs(self, tmp_path: Path) -> None:
        # 执行失败型 run：无清单无报告，agent_logs 有 error 事件
        run_dir = tmp_path / "runs" / "20260831_120808"
        (run_dir / "agent_logs").mkdir(parents=True)
        (run_dir / "agent_logs" / "agent_t1.jsonl").write_text(
            json.dumps(
                {
                    "event": "error",
                    "error_message": "凭证未配置: AGENT_SERVER.username"
                    "（sut_config 引用 credential_ref='AGENT_SERVER'）",
                },
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        scanned = runs.scan_runs(tmp_path)
        assert scanned[0]["status"] == "执行失败"
        assert "凭证未配置" in scanned[0]["error"]

    def test_scan_status_executed_without_eval(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "runs" / "20260831_130000"
        (run_dir / "packages").mkdir(parents=True)
        (run_dir / "run_manifest.json").write_text(
            json.dumps({"mode": "run", "package_ref": "chat"}), encoding="utf-8"
        )
        assert runs.scan_runs(tmp_path)[0]["status"] == "已执行"

    def test_show_failed_run_diagnostics(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        run_dir = tmp_path / "runs" / "20260831_120808"
        (run_dir / "agent_logs").mkdir(parents=True)
        (run_dir / "agent_logs" / "agent_t1.jsonl").write_text(
            json.dumps(
                {
                    "event": "error",
                    "error_message": "凭证未配置: AGENT_SERVER.username"
                    "（sut_config 引用 credential_ref='AGENT_SERVER'）",
                },
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        monkeypatch.setenv("WORKSPACE_DIR", str(tmp_path))
        result = runner.invoke(runs.runs_app, ["show", "20260831_120808"])
        assert result.exit_code == 0, result.output
        assert "执行失败" in result.output and "失败原因" in result.output
        assert "secrets set AGENT_SERVER.username" in result.output  # 可操作引导

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


# ── secrets 工作台向导 ──────────────────────────────────────────────────


class TestSecretsWizard:
    def test_wizard_set_view_roundtrip(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import json

        from agent_eval.cli.cmds.secrets import secrets_wizard
        from agent_eval.cli.console import prompts

        cred = tmp_path / "creds.json"
        monkeypatch.setenv("AGENT_EVAL_SUT_CREDENTIALS", str(cred))
        picks = iter(["录入 / 更新凭证", "password", "查看已录凭证", "返回"])
        answers = iter(["AGENT_SERVER", "pw-123"])  # ref（无存量→ask）→ 值（隐藏）
        monkeypatch.setattr(prompts, "select", lambda label, options, **kw: next(picks))
        monkeypatch.setattr(prompts, "ask", lambda label, **kw: next(answers))

        secrets_wizard()

        saved = json.loads(cred.read_text(encoding="utf-8"))
        assert saved == {"AGENT_SERVER": {"password": "pw-123"}}

    def test_wizard_delete(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import json

        from agent_eval.cli.cmds.secrets import secrets_wizard
        from agent_eval.cli.console import prompts

        cred = tmp_path / "creds.json"
        cred.write_text(json.dumps({"SASAN": {"username": "u", "password": "p"}}), encoding="utf-8")
        monkeypatch.setenv("AGENT_EVAL_SUT_CREDENTIALS", str(cred))
        picks = iter(["删除凭证", "SASAN.password", "返回"])
        monkeypatch.setattr(prompts, "select", lambda label, options, **kw: next(picks))
        monkeypatch.setattr(prompts, "confirm", lambda label, **kw: True)

        secrets_wizard()

        saved = json.loads(cred.read_text(encoding="utf-8"))
        assert saved == {"SASAN": {"username": "u"}}  # 只删所选字段

    def test_wizard_view_empty(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from agent_eval.cli.cmds.secrets import secrets_wizard
        from agent_eval.cli.console import prompts

        monkeypatch.setenv("AGENT_EVAL_SUT_CREDENTIALS", str(tmp_path / "creds.json"))
        picks = iter(["查看已录凭证", "返回"])
        monkeypatch.setattr(prompts, "select", lambda label, options, **kw: next(picks))

        secrets_wizard()  # 空库不抛、可见提示


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
        assert "行" in result.output and "合计" in result.output  # 行数 + 汇总（F-C-SCN-VIEW-01）
        assert "task_sets/" in result.output  # 按目录分组

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

    def test_new_agent_mode_requires_llm(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # agent 模式就绪检查失败 → 给出可操作指引（F-NF-C-03 降级，非 traceback）
        from agent_eval.core.exceptions import AgentError

        def _fail(role: str, *args: object, **kwargs: object) -> None:
            raise AgentError(f"角色 {role} 未配置")

        monkeypatch.setattr("agent_eval.agent.model_bridge.build_chat_model", _fail)
        result = runner.invoke(
            scenario_app, ["new", "x/y", "--mode", "agent", "--output", str(tmp_path / "p")]
        )
        assert result.exit_code == 1
        assert "models set" in result.output

    def test_new_rejects_unimplemented_mode(self, tmp_path: Path) -> None:
        result = runner.invoke(
            scenario_app, ["new", "x/y", "--mode", "template", "--output", str(tmp_path / "p")]
        )
        assert result.exit_code == 1

    def test_new_skeleton_requires_ref(self) -> None:
        result = runner.invoke(scenario_app, ["new", "--mode", "skeleton"])
        assert result.exit_code == 2
        assert "需要 REF" in result.output


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


# ── 回归：向导直调动作不得泄漏 typer.OptionInfo（workbench 执行域崩溃修复） ──


class _WizardStubs:
    """monkeypatch _stages 各阶段 + run_id 生成，隔离真实执行。"""

    def __init__(self, tmp_path: Path) -> None:
        from types import SimpleNamespace

        pkg = SimpleNamespace(manifest=SimpleNamespace(ref="chat/chat:1.0.0"), root=tmp_path)
        self.inputs = SimpleNamespace(
            task_set_path=str(tmp_path / "default.yaml"),
            task_set_model=SimpleNamespace(tasks=[{}, {}]),
            sut=SimpleNamespace(name="sasan-agent", channel="agent_protocol", base_url="http://x"),
            resolved_pkg=pkg,
        )
        self.calls: dict[str, dict] = {}

    def no_options_info(self, kwargs: dict) -> None:
        """任何参数值都不得是 typer.OptionInfo（回归断言核心）。"""
        for key, value in kwargs.items():
            assert not type(value).__name__.endswith("OptionInfo"), f"参数 {key} 泄漏 OptionInfo"

    def patch(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import agent_eval.cli._stages as stages
        import agent_eval.storage.package as storage_pkg

        monkeypatch.setattr(stages, "resolve_run_inputs", lambda *a, **k: self.inputs)
        monkeypatch.setattr(
            stages, "resolve_eval_inputs", lambda *a, **k: "/tmp/rules/chat-quality.yaml"
        )
        monkeypatch.setattr(stages, "build_judge_context", lambda *a, **k: object())
        monkeypatch.setattr(
            stages,
            "execute_stage",
            lambda *a, **k: (self.calls.setdefault("execute", dict(k)), [])[1],
        )
        monkeypatch.setattr(
            stages,
            "evaluate_stage",
            lambda *a, **k: (self.calls.setdefault("evaluate", dict(k)), object())[1],
        )
        monkeypatch.setattr(
            stages,
            "finalize_eval",
            lambda *a, **k: self.calls.setdefault("finalize", dict(k)),
        )
        monkeypatch.setattr(storage_pkg, "generate_run_id", lambda: "20260101_000000")


class TestExecuteActionDirectCall:
    def test_execute_pipeline_minimal_kwargs(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """向导以最小 kwargs 直调（未传参数不得保留 OptionInfo 默认值）。"""
        from agent_eval.cli.cmds.execute import execute_pipeline

        monkeypatch.setenv("WORKSPACE_DIR", str(tmp_path))
        stubs = _WizardStubs(tmp_path)
        stubs.patch(monkeypatch)

        execute_pipeline(package="chat", task_set="default", sut_name="sasan-agent")
        # 执行阶段参数：llm_role/max_turns 为真实 None，workspace_root 为 Path
        assert stubs.calls["execute"]["llm_role"] is None
        assert stubs.calls["execute"]["max_turns"] is None
        assert isinstance(stubs.calls["execute"]["workspace_root"], Path)
        stubs.no_options_info(stubs.calls["execute"])
        stubs.no_options_info(stubs.calls["evaluate"])
        stubs.no_options_info(stubs.calls["finalize"])

    def test_execute_run_minimal_kwargs(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from agent_eval.cli.cmds.execute import execute_run

        monkeypatch.chdir(tmp_path)
        stubs = _WizardStubs(tmp_path)
        stubs.patch(monkeypatch)

        execute_run(package="chat", task_set="default", sut_name="sasan-agent")
        assert stubs.calls["execute"]["llm_role"] is None
        stubs.no_options_info(stubs.calls["execute"])

    def test_wizard_exec_domain_invokes_action(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """向导执行域全链路（选包→考卷→SUT→规则集→模式→确认）打到动作层。"""
        from agent_eval.cli.main import app

        monkeypatch.setenv("WORKSPACE_DIR", str(tmp_path))
        stubs = _WizardStubs(tmp_path)
        stubs.patch(monkeypatch)

        # 2 执行评测 → 1 chat 包 → 1 default 考卷 → 1 SUT → 1 规则集 → 1 pipeline → y 确认 → 5 退出
        result = runner.invoke(app, ["start"], input="2\n1\n1\n1\n1\n1\ny\n5\n")
        assert result.exit_code == 0, result.output
        assert "等价命令" in result.output
        # 动作层被真实调用且未崩溃（此前在此处报 OptionInfo TypeError）
        assert "execute" in stubs.calls
        assert "配置加载失败" not in result.output
        stubs.no_options_info(stubs.calls["execute"])


# ── 无参交互选择（查看类命令缺参不报 Usage 错，gh run view 同款路径） ──


class TestNoArgInteractiveSelect:
    def test_scenario_show_no_arg_selects_first(self) -> None:
        result = runner.invoke(scenario_app, ["show"], input="1\n")
        assert result.exit_code == 0, result.output
        assert "选择场景包" in result.output
        assert "chat" in result.output  # 内置包 1 号

    def test_scenario_show_no_arg_no_input_exits_2(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AGENT_EVAL_NO_INPUT", "1")
        result = runner.invoke(scenario_app, ["show"])
        assert result.exit_code == 2
        assert "缺少必需输入" in result.output

    def test_scenario_show_no_arg_env_bypass(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AGENT_EVAL_NO_INPUT", "1")
        monkeypatch.setenv("AGENT_EVAL_SCENARIO_REF", "chat")
        result = runner.invoke(scenario_app, ["show", "--section", "manifest"])
        assert result.exit_code == 0, result.output

    def test_runs_show_no_arg_selects_latest(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _make_run(tmp_path, "20260831_093012")
        monkeypatch.setenv("WORKSPACE_DIR", str(tmp_path))
        result = runner.invoke(runs.runs_app, ["show"], input="1\n")
        assert result.exit_code == 0, result.output
        assert "选择运行" in result.output
        assert "0.780" in result.output

    def test_runs_show_no_arg_empty_ws_exits_1(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("WORKSPACE_DIR", str(tmp_path))
        result = runner.invoke(runs.runs_app, ["show"])
        assert result.exit_code == 1
        assert "无运行记录" in result.output

    def test_runs_show_no_arg_env_bypass(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _make_run(tmp_path, "20260831_093012")
        monkeypatch.setenv("WORKSPACE_DIR", str(tmp_path))
        monkeypatch.setenv("AGENT_EVAL_NO_INPUT", "1")
        monkeypatch.setenv("AGENT_EVAL_RUN_ID", "20260831_093012")
        result = runner.invoke(runs.runs_app, ["show"])
        assert result.exit_code == 0, result.output
