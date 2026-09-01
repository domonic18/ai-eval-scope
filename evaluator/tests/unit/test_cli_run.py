"""CLI `run` 命令测试（arch/03 Phase B：task_set + sut_config → 执行包）。"""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from agent_eval.cli.main import app

runner = CliRunner()

TASK_SET_YAML = """
id: ts_cli
name: CLI 冒烟任务集
tasks:
  - id: t_cli_1
    input:
      subject: math
      grade: seven
"""

SUT_YAML = """
sut:
  name: cw-agent
  channel: agent_protocol
  base_url: https://ap.example.com
"""


class FakeExecutionAgent:
    """替身：不依赖 deepagents，直接复用真实 write_package 产包。"""

    def __init__(self, config, sut_tools=None, extra_tool_servers=None):
        self.config = config
        from agent_eval.agent.sut_tools import SUTToolServer
        from agent_eval.storage.package import ExecutionPackage

        self._sut_tools = SUTToolServer(workspace_dir=self.config.workspace_dir)
        self._package_cls = ExecutionPackage
        self.extra_tool_servers = extra_tool_servers or []

    async def run_task_set(self, task_set, *, run_id: str | None = None):
        packages_root = Path(self.config.workspace_dir) / "runs" / (run_id or "r_fake") / "packages"
        packages = []
        for task in task_set.tasks:
            self._sut_tools.workspace_dir = packages_root
            await self._sut_tools.write_package(
                task_id=task.id,
                success=True,
                trace={"request": {}, "response": {}, "started_at": "t", "finished_at": "t"},
                metrics={"tool_calls": 0},
            )
            packages.append(self._package_cls.load(packages_root / task.id))
        return run_id or "r_fake", packages


def test_run_command_produces_packages(tmp_path, monkeypatch) -> None:
    task_set = tmp_path / "task_set.yaml"
    sut_cfg = tmp_path / "sut.yaml"
    out_dir = tmp_path / "out"
    task_set.write_text(TASK_SET_YAML, encoding="utf-8")
    sut_cfg.write_text(SUT_YAML, encoding="utf-8")

    import agent_eval.agent.execution_agent as execution_agent_mod

    monkeypatch.setattr(execution_agent_mod, "ExecutionAgent", FakeExecutionAgent)

    result = runner.invoke(
        app,
        [
            "run",
            "--task-set",
            str(task_set),
            "--sut-config",
            str(sut_cfg),
            "--output-dir",
            str(out_dir),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "cw-agent" in result.output
    assert "1/1 成功" in result.output
    import re

    rid = re.search(r"运行 ID: (\S+)", result.output).group(1)
    assert (
        out_dir / "runs" / rid / "packages" / "t_cli_1" / "manifest.json"
    ).exists()  # W7：包归位
    assert (out_dir / "runs" / rid / "packages" / "t_cli_1" / "metrics.json").exists()
    # 输出包含下一步评估提示
    assert "agent-eval eval --package-dir" in result.output


SUT_AUTH_YAML = (
    SUT_YAML
    + """
  auth:
    type: static_token
    credential_ref: NEEDS_KEY
"""
)


def test_run_command_fills_missing_credentials_before_progress(tmp_path, monkeypatch) -> None:
    """凭证缺失在进度视图启动前引导补录（实测反馈：提示被进度转轮刷掉）。"""
    from agent_eval.execution.auth.secrets_store import load_secrets_file

    task_set = tmp_path / "task_set.yaml"
    sut_cfg = tmp_path / "sut.yaml"
    task_set.write_text(TASK_SET_YAML, encoding="utf-8")
    sut_cfg.write_text(SUT_AUTH_YAML, encoding="utf-8")

    import agent_eval.agent.execution_agent as execution_agent_mod

    monkeypatch.setattr(execution_agent_mod, "ExecutionAgent", FakeExecutionAgent)
    monkeypatch.setattr("agent_eval.cli.console.prompts.confirm", lambda *a, **k: True)
    monkeypatch.setattr("agent_eval.cli.console.prompts.ask", lambda *a, **k: "tk-1")

    result = runner.invoke(
        app,
        [
            "run",
            "--task-set",
            str(task_set),
            "--sut-config",
            str(sut_cfg),
            "--output-dir",
            str(tmp_path / "out"),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "缺少凭证" in result.output
    assert load_secrets_file()["NEEDS_KEY"] == {"token": "tk-1"}  # 补录落盘后继续执行


def test_run_command_declined_fill_exits_clean_without_run(tmp_path, monkeypatch) -> None:
    task_set = tmp_path / "task_set.yaml"
    sut_cfg = tmp_path / "sut.yaml"
    task_set.write_text(TASK_SET_YAML, encoding="utf-8")
    sut_cfg.write_text(SUT_AUTH_YAML, encoding="utf-8")
    monkeypatch.setattr("agent_eval.cli.console.prompts.confirm", lambda *a, **k: False)

    out_dir = tmp_path / "out"
    result = runner.invoke(
        app,
        [
            "run",
            "--task-set",
            str(task_set),
            "--sut-config",
            str(sut_cfg),
            "--output-dir",
            str(out_dir),
        ],
    )
    assert result.exit_code == 1
    assert "凭证缺失" in result.output
    assert not out_dir.exists()  # run_id 尚未生成，不留半截运行目录


def test_run_command_rejects_unscheduled_channel(tmp_path) -> None:
    task_set = tmp_path / "task_set.yaml"
    sut_cfg = tmp_path / "sut.yaml"
    task_set.write_text(TASK_SET_YAML, encoding="utf-8")
    sut_cfg.write_text(SUT_YAML.replace("agent_protocol", "generic_http"), encoding="utf-8")
    result = runner.invoke(app, ["run", "--task-set", str(task_set), "--sut-config", str(sut_cfg)])
    assert result.exit_code == 1
    assert "预留未排期" in result.output


def test_run_command_missing_task_set(tmp_path) -> None:
    sut_cfg = tmp_path / "sut.yaml"
    sut_cfg.write_text(SUT_YAML, encoding="utf-8")
    result = runner.invoke(
        app, ["run", "--task-set", str(tmp_path / "ghost.yaml"), "--sut-config", str(sut_cfg)]
    )
    assert result.exit_code == 1
    assert "配置加载失败" in result.output


def test_run_command_multi_sut_requires_name(tmp_path) -> None:
    task_set = tmp_path / "task_set.yaml"
    task_set.write_text(TASK_SET_YAML, encoding="utf-8")
    sut_dir = tmp_path / "suts"
    sut_dir.mkdir()
    (sut_dir / "a.yaml").write_text(SUT_YAML, encoding="utf-8")
    (sut_dir / "b.yaml").write_text(SUT_YAML.replace("cw-agent", "other-agent"), encoding="utf-8")
    result = runner.invoke(app, ["run", "--task-set", str(task_set), "--sut-config", str(sut_dir)])
    assert result.exit_code == 1
    assert "显式指定" in result.output

    result_named = runner.invoke(
        app,
        [
            "run",
            "--task-set",
            str(task_set),
            "--sut-config",
            str(sut_dir),
            "--sut-name",
            "other-agent",
        ],
    )
    # 命中系统名后进入执行阶段（FakeExecutionAgent 未注入 → deepagents 缺失报错也算到达）
    assert "other-agent" in result_named.output


def test_run_command_closes_channel_same_loop(tmp_path, monkeypatch) -> None:
    """通道 aclose 必须与 run 同一 event loop 恰好执行一次（v4.6.3 收尾修复）。"""
    task_set = tmp_path / "task_set.yaml"
    sut_cfg = tmp_path / "sut.yaml"
    out_dir = tmp_path / "out"
    task_set.write_text(TASK_SET_YAML, encoding="utf-8")
    sut_cfg.write_text(SUT_YAML, encoding="utf-8")

    import agent_eval.agent.execution_agent as execution_agent_mod
    from agent_eval.execution.channels import base as channels_base

    monkeypatch.setattr(execution_agent_mod, "ExecutionAgent", FakeExecutionAgent)

    calls: list[str] = []

    class FakeChannel:
        async def aclose(self) -> None:
            calls.append("aclose")

    monkeypatch.setattr(channels_base, "create_channel", lambda sut: FakeChannel())

    result = runner.invoke(
        app,
        [
            "run",
            "--task-set",
            str(task_set),
            "--sut-config",
            str(sut_cfg),
            "--output-dir",
            str(out_dir),
        ],
    )
    assert result.exit_code == 0, result.output
    assert calls == ["aclose"]
