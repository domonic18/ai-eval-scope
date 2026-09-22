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

    def test_run_detail_pure_data(self, tmp_path: Path) -> None:
        """run_detail（Sprint 14b 提纯，Agent 执行域复用）：纯数据 + 缺目录 None。"""
        assert runs.run_detail("nope", tmp_path) is None

        _make_run(tmp_path, "20260831_093012")
        detail = runs.run_detail("20260831_093012", tmp_path)
        assert detail is not None
        assert detail["run_id"] == "20260831_093012"
        assert detail["summary"]["metrics"]["chat:reward"] == 0.78
        assert detail["manifest"]["mode"] == "pipeline"
        assert str(tmp_path) in detail["run_dir"]


# ── 账号域：平台账号 (auth) 入口 ────────────────────────────────────────


class TestAccountDomain:
    def test_account_opens_auth_wizard(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import agent_eval.cli.cmds.auth as auth_mod
        import agent_eval.cli.workbench.domains.account as account_mod

        called: list[bool] = []
        refreshed: list[int] = []

        class _Session:
            def _refresh(self) -> None:
                refreshed.append(1)

        picks = iter(["平台账号 (auth)"])
        monkeypatch.setattr(account_mod, "select", lambda label, options, **kw: next(picks, "返回"))
        monkeypatch.setattr(auth_mod, "auth_wizard", lambda: called.append(True))

        account_mod.main(_Session())
        assert called == [True]
        assert refreshed == [1]  # 登录动作后刷新平台态（banner ✅）

    def test_start_domain_auth_alias(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import agent_eval.cli.workbench.domains.account as account_mod
        from agent_eval.cli.main import app

        hit: list[str] = []
        monkeypatch.setattr(account_mod, "main", lambda s: hit.append("auth"))
        result = runner.invoke(app, ["start", "--domain", "auth"])
        assert result.exit_code == 0
        assert hit == ["auth"]  # --domain auth 别名直达账号域（arch/15 §13）

    def test_start_domain_agent_entry(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # §3.5：--domain agent 直达工作台 Agent 一级入口；主菜单首项为推荐入口
        from agent_eval.cli.cmds import workbench_agent as wb
        from agent_eval.cli.main import app
        from agent_eval.cli.workbench.session import _DOMAINS

        hit: list[str] = []
        monkeypatch.setattr(wb, "agent_workbench_entry", lambda s=None: hit.append("agent"))
        result = runner.invoke(app, ["start", "--domain", "agent"])
        assert result.exit_code == 0
        assert hit == ["agent"]
        assert _DOMAINS[0][0] == "agent"  # 一级入口居首（首选工作方式）

    def test_agent_entry_blocks_without_llm(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Agent 入口 preflight 阻断：LLM 未配置 → 指引 models set（区别于查看类只提示）
        import typer

        from agent_eval.cli.cmds import workbench_agent as wb
        from agent_eval.cli.main import app

        def boom() -> None:
            raise typer.Exit(code=1)

        monkeypatch.setattr(wb, "_guard_llm_ready", boom)
        result = runner.invoke(app, ["start", "--domain", "agent"])
        assert result.exit_code == 1

    def test_scn_menu_labels_are_profile_shortcuts(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # §3.5：域内两项标签 = 档位快捷方式（「用 Agent …」）
        import agent_eval.cli.workbench.domains.scn as scn_mod

        picked: list[list[str]] = []

        def fake_select(label: str, options: list[str], **kw: object) -> str:
            picked.append(options)
            return "返回"

        monkeypatch.setattr(scn_mod, "select", fake_select)
        scn_mod.main(session=None)
        labels = picked[0]
        assert "用 Agent 创建场景包" in labels
        assert "用 Agent 修改选中的包" in labels
        assert not any(label == "Agent 会话改包" for label in labels)


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
        picks = iter(["录入 / 更新凭证", "➕ 新增 ref…", "查看已录凭证", "返回"])
        answers = iter(["AGENT_SERVER", "password", "pw-123"])  # 新 ref → 字段（自由输入）→ 值
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

        monkeypatch.setattr("agent_eval.agent.core.model_bridge.build_chat_model", _fail)
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


class TestOnboarding:
    """start 首启引导（v4.15）：模型未配置 → 引导卡 + 一步直达 models set。"""

    @staticmethod
    def _session(monkeypatch: pytest.MonkeyPatch, *, configured: bool):
        from types import SimpleNamespace

        from agent_eval.cli.workbench.session import WorkbenchSession

        monkeypatch.delenv("AGENT_EVAL_HOST", raising=False)
        monkeypatch.delenv("AGENT_EVAL_API_KEY", raising=False)
        cfg = (
            SimpleNamespace(roles={"text": SimpleNamespace(model="kimi-k2")})
            if configured
            else None
        )
        monkeypatch.setattr("agent_eval.config.llm_file.load_llm_file", lambda: cfg)
        return WorkbenchSession()

    def test_guide_card_and_defer(self, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
        """未配置 → 引导卡（影响面 + 所需准备）+ 稍后不拉起向导。"""
        s = self._session(monkeypatch, configured=False)
        monkeypatch.setattr(
            "agent_eval.cli.workbench.session.select",
            lambda *a, **k: "稍后——菜单「账号与配置」随时可配",
        )
        calls: list[str] = []
        monkeypatch.setattr("agent_eval.cli.cmds.models.models_set", lambda: calls.append("set"))
        s.onboard()
        out = capsys.readouterr().out
        assert "模型尚未配置" in out and "欢迎使用 agent-eval" in out
        assert "API Key" in out and "场景包管理" in out  # 影响面与准备项可见
        assert calls == []  # 稍后不拉向导

    def test_setup_now_invokes_wizard_and_reports_ready(
        self, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        """立即配置 → 直达 models set；配置后正反馈（无需去账号域找）。"""
        from types import SimpleNamespace

        s = self._session(monkeypatch, configured=False)
        box = {"configured": False}

        def llm_file():
            # 模拟「配置成功落盘」：fake_set 置位后 _refresh 读到已配置
            if box["configured"]:
                return SimpleNamespace(roles={"text": SimpleNamespace(model="kimi-k2")})
            return None

        monkeypatch.setattr("agent_eval.config.llm_file.load_llm_file", llm_file)
        monkeypatch.setattr(
            "agent_eval.cli.workbench.session.select",
            lambda *a, **k: "立即配置（推荐）",
        )
        calls: list[str] = []

        def fake_set() -> None:
            calls.append("set")
            box["configured"] = True

        monkeypatch.setattr("agent_eval.cli.cmds.models.models_set", fake_set)
        s.onboard()
        assert calls == ["set"]
        assert "模型已就绪" in capsys.readouterr().out

    def test_setup_cancel_falls_back_not_crash(
        self, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        """向导中途取消（typer.Exit/Abort）→ 回落主菜单语义，不整场退出。"""

        def cancel() -> None:
            raise typer.Exit(code=1)

        s = self._session(monkeypatch, configured=False)
        monkeypatch.setattr(
            "agent_eval.cli.workbench.session.select",
            lambda *a, **k: "立即配置（推荐）",
        )
        monkeypatch.setattr("agent_eval.cli.cmds.models.models_set", cancel)
        s.onboard()  # 不抛
        assert "配置未完成" in capsys.readouterr().out

    def test_menu_labels_marked_when_model_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        entries = self._session(monkeypatch, configured=False)._menu_entries()
        labels = dict(entries)
        assert "需先配置模型" in labels["agent"]
        assert "需先配置模型" in labels["exec"]
        assert "需先配置模型" not in labels["scn"]  # 本地功能不受影响，不吓唬用户
        configured = self._session(monkeypatch, configured=True)._menu_entries()
        assert all("需先配置模型" not in label for _, label in configured)


# ── 回归：向导直调动作不得泄漏 typer.OptionInfo（workbench 执行域崩溃修复） ──


class _WizardStubs:
    """monkeypatch _stages 各阶段 + run_id 生成，隔离真实执行。"""

    def __init__(self, tmp_path: Path) -> None:
        from types import SimpleNamespace

        pkg = SimpleNamespace(
            manifest=SimpleNamespace(ref="chat/chat:1.0.0", id="chat"), root=tmp_path
        )
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
        from types import SimpleNamespace

        import agent_eval.cli._stages as stages
        import agent_eval.storage.package as storage_pkg

        # 上报隔离：仓库 .env 的 AGENT_EVAL_UPLOAD=true 会渗入 pipeline 直调测试
        # （core 内联上报段真发平台，禁联网）——显式钉死为关
        monkeypatch.setenv("AGENT_EVAL_UPLOAD", "0")
        # 模型配置态自足：无 ~/.agent_eval/llm.json 的环境（CI/新机）start 首启
        # 引导卡会弹出并吃掉喂给向导的输入序列——钉死为已配置
        cfg = SimpleNamespace(roles={"text": SimpleNamespace(model="kimi-k2")})
        monkeypatch.setattr("agent_eval.config.llm_file.load_llm_file", lambda: cfg)
        monkeypatch.setattr(stages, "resolve_run_inputs", lambda *a, **k: self.inputs)
        monkeypatch.setattr(
            stages, "resolve_eval_inputs", lambda *a, **k: "/tmp/rules/chat-quality.yaml"
        )
        monkeypatch.setattr(stages, "build_judge_context", lambda *a, **k: object())
        # pipeline_core 成功路径触达 result.report/samples/gate（终态 payload+回填）
        from types import SimpleNamespace

        fake_result = SimpleNamespace(
            samples=[],
            report=SimpleNamespace(metrics={}, total_samples=0),
            gate={"mode": "off", "enabled": False, "passed": True},
        )
        monkeypatch.setattr(
            stages,
            "execute_stage",
            lambda *a, **k: (self.calls.setdefault("execute", dict(k)), [])[1],
        )
        monkeypatch.setattr(
            stages,
            "evaluate_stage",
            lambda *a, **k: (self.calls.setdefault("evaluate", dict(k)), fake_result)[1],
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
        # pipeline 已不经 finalize_eval（core 事件序自编排，arch/15 v4.12）——
        # 上报等价面 observability_flush 的回归在 test_cli_pipeline 门禁用例

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

        # 3 执行评测 → 1 chat 包 → 1 default 考卷 → 1 SUT → 1 规则集 → 1 pipeline
        # → 1 normal 日志档位 → y 确认 → 6 退出
        # （主菜单首位是工作台 Agent 一级入口，arch/15 §3.5）
        result = runner.invoke(app, ["start"], input="3\n1\n1\n1\n1\n1\n1\ny\n6\n")
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


# ── 执行评测域：通道排期前置预检 ────────────────────────────────────────


class TestExecDomain:
    @staticmethod
    def _make_pkg(tmp_path: Path, channel: str) -> None:
        (tmp_path / "task_sets").mkdir(parents=True)
        (tmp_path / "sut_configs").mkdir()
        (tmp_path / "rules").mkdir()
        (tmp_path / "task_sets" / "basic.yaml").write_text("tasks:\n  - id: a\n", encoding="utf-8")
        (tmp_path / "sut_configs" / "api.yaml").write_text(
            f"sut:\n  name: api\n  channel: {channel}\n  base_url: https://api.example.com\n",
            encoding="utf-8",
        )
        (tmp_path / "rules" / "quality.yaml").write_text("rules: []\n", encoding="utf-8")

    @staticmethod
    def _patch_pkgs(monkeypatch: pytest.MonkeyPatch, root: Path) -> None:
        from types import SimpleNamespace

        pkg = SimpleNamespace(
            manifest=SimpleNamespace(ref="t/api", default_task_set="basic", default_rule_set=None),
            source="project",
            root=root,
        )
        monkeypatch.setattr("agent_eval.packages.PackageManager.list", lambda self: [pkg])

    @staticmethod
    def _session() -> object:
        from types import SimpleNamespace

        class _Session:
            ctx = SimpleNamespace(active_package=None, active_task_set=None, active_sut=None)

        return _Session()

    def test_exec_prescreens_unscheduled_channel(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """选 SUT 后即预检通道排期：未排期立即报错返回，不进执行摘要与执行器
        （旧链路答完 5 个交互才在 create_channel 工厂报错）。"""
        import agent_eval.cli.cmds.execute as execute_mod
        import agent_eval.cli.workbench.domains.exec as exec_mod

        self._make_pkg(tmp_path, "browser")
        self._patch_pkgs(monkeypatch, tmp_path)
        picks = iter(["t/api  (project)", "basic（1 任务）", "api（browser）"])
        monkeypatch.setattr(exec_mod, "select", lambda label, options, **kw: next(picks))
        called: list[str] = []
        monkeypatch.setattr(execute_mod, "execute_pipeline", lambda **kw: called.append("pipeline"))
        monkeypatch.setattr(execute_mod, "execute_run", lambda **kw: called.append("run"))

        exec_mod.main(self._session())
        assert "预留未排期" in capsys.readouterr().out
        assert called == []
        assert self._session().ctx.active_sut is None

    def test_exec_annotates_channel_and_passes_prescreen(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """SUT 选项带通道标注；排期通道放行并按 stem 正确传参。"""
        import agent_eval.cli.cmds.execute as execute_mod
        import agent_eval.cli.workbench.domains.exec as exec_mod

        self._make_pkg(tmp_path, "agent_protocol")
        self._patch_pkgs(monkeypatch, tmp_path)
        picks = iter(
            [
                "t/api  (project)",
                "basic（1 任务）",
                "api（agent_protocol）",
                "quality",
                "pipeline（执行 + 评估 + 报告）",
                "normal（默认进度）",
            ]
        )
        seen_options: dict[str, list[str]] = {}
        monkeypatch.setattr(
            exec_mod,
            "select",
            lambda label, options, **kw: (
                seen_options.update({label: options}),
                next(picks),
            )[1],
        )
        monkeypatch.setattr(exec_mod, "confirm", lambda label, **kw: True)
        called: dict = {}
        monkeypatch.setattr(execute_mod, "execute_pipeline", lambda **kw: called.update(kw))

        session = self._session()
        exec_mod.main(session)
        assert "api（agent_protocol）" in seen_options["选择 SUT"]  # 选项带通道标注
        assert called["sut_name"] == "api"  # stem 从「api（agent_protocol）」正确解析回取
        assert called["package"] == "t/api"
        assert session.ctx.active_sut == "api"


# ── Agent 会话宿主：SIGINT 协作中断分流（Sprint 14b）───────────────────


class TestGracefulExecInterrupt:
    """`_graceful_exec_interrupt` handler 直调函数体测试（真实 os.kill 放 e2e，默认 skip）。"""

    @staticmethod
    def _agent(active: bool = True) -> object:
        class _FakeAgent:
            def __init__(self) -> None:
                self.interrupts = 0

            def interrupt_active_execution(self) -> bool:
                self.interrupts += 1
                return active

        return _FakeAgent()

    def test_first_press_cooperative_second_press_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import signal

        from agent_eval.cli.cmds import workbench_agent as wb

        monkeypatch.setattr(wb, "rprint", lambda *a, **k: None)  # 静音黄字提示
        previous = signal.getsignal(signal.SIGINT)
        agent = self._agent(active=True)
        with wb._graceful_exec_interrupt(agent):
            handler = signal.getsignal(signal.SIGINT)
            assert handler is not previous
            handler(signal.SIGINT, None)  # 首按：协作取消，不抛 KI
            assert agent.interrupts == 1
            with pytest.raises(KeyboardInterrupt):
                handler(signal.SIGINT, None)  # 二按：屏蔽后续信号，走现行暂停语义
            assert signal.getsignal(signal.SIGINT) is signal.SIG_IGN  # teardown 期屏蔽按键风暴
            assert agent.interrupts == 1  # 二按不再置位
        assert signal.getsignal(signal.SIGINT) is previous  # 退出复原（屏蔽解除）

    def test_first_press_without_active_execution_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import signal

        from agent_eval.cli.cmds import workbench_agent as wb

        monkeypatch.setattr(wb, "rprint", lambda *a, **k: None)
        agent = self._agent(active=False)  # 无活跃执行
        with wb._graceful_exec_interrupt(agent):
            handler = signal.getsignal(signal.SIGINT)
            with pytest.raises(KeyboardInterrupt):
                handler(signal.SIGINT, None)  # 首按即走现行暂停语义（同样先屏蔽）
            assert signal.getsignal(signal.SIGINT) is signal.SIG_IGN
        assert agent.interrupts == 1
