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

        self._sut_tools = SUTToolServer()
        self._package_cls = ExecutionPackage
        self.extra_tool_servers = extra_tool_servers or []

    async def run_task_set(self, task_set):
        packages = []
        for task in task_set.tasks:
            await self._sut_tools.write_package(
                workspace_dir=str(self.config.workspace_dir),
                task_id=task.id,
                success=True,
                trace={"request": {}, "response": {}, "started_at": "t", "finished_at": "t"},
                metrics={"tool_calls": 0},
            )
            packages.append(self._package_cls.load(Path(self.config.workspace_dir) / task.id))
        return packages


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
    assert (out_dir / "t_cli_1" / "manifest.json").exists()
    assert (out_dir / "t_cli_1" / "metrics.json").exists()
    # 输出包含下一步评估提示
    assert "agent-eval eval --package-dir" in result.output


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
