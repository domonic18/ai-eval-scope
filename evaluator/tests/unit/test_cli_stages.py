"""cli/_stages 共享编排段测试（Sprint 9：run/eval/suite/pipeline 收敛）。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_eval.cli._stages import (
    JudgeContext,
    evaluate_stage,
    execute_stage,
    resolve_run_inputs,
)
from agent_eval.core.exceptions import AgentEvalError, SUTAuthError

TASK_SET_YAML = """
id: ts_stages
name: 阶段测试
tasks:
  - id: t_1
    input:
      subject: math
"""
SUT_YAML = """
sut:
  name: cw-agent
  channel: agent_protocol
  base_url: https://ap.example.com
"""


class FakeExecutionAgent:
    """替身：复用真实 write_package 产包（同 test_cli_run 范式）。"""

    def __init__(self, config, sut_tools=None, extra_tool_servers=None):
        self.config = config
        from agent_eval.agent.sut_tools import SUTToolServer
        from agent_eval.storage.package import ExecutionPackage

        self._sut_tools = SUTToolServer(workspace_dir=self.config.workspace_dir)
        self._package_cls = ExecutionPackage
        self.extra_tool_servers = extra_tool_servers or []

    async def run_task_set(self, task_set, *, run_id: str | None = None):
        packages_root = Path(self.config.workspace_dir) / "runs" / (run_id or "r") / "packages"
        packages = []
        for task in task_set.tasks:
            self._sut_tools.workspace_dir = packages_root
            await self._sut_tools.write_package(
                task_id=task.id,
                success=True,
                trace={"request": {}, "response": {}},
                metrics={"tool_calls": 0},
            )
            packages.append(self._package_cls.load(packages_root / task.id))
        return run_id or "r", packages


class TestResolveRunInputs:
    def test_missing_task_set_and_package_raises(self) -> None:
        with pytest.raises(AgentEvalError, match="task-set"):
            resolve_run_inputs(None)

    def test_missing_sut_config_and_package_raises(self, tmp_path: Path) -> None:
        task_set = tmp_path / "task_set.yaml"
        task_set.write_text(TASK_SET_YAML, encoding="utf-8")
        with pytest.raises(AgentEvalError, match="sut-config"):
            resolve_run_inputs(None, task_set=str(task_set))

    def test_explicit_paths_resolve(self, tmp_path: Path) -> None:
        task_set = tmp_path / "task_set.yaml"
        sut_cfg = tmp_path / "sut.yaml"
        task_set.write_text(TASK_SET_YAML, encoding="utf-8")
        sut_cfg.write_text(SUT_YAML, encoding="utf-8")
        inputs = resolve_run_inputs(None, task_set=str(task_set), sut_config=str(sut_cfg))
        assert inputs.resolved_pkg is None
        assert len(inputs.task_set_model.tasks) == 1
        assert inputs.sut.name == "cw-agent"


class FakeChannel:
    async def aclose(self) -> None:
        pass


class TestExecuteStage:
    def test_writes_run_manifest_with_mode(self, tmp_path, monkeypatch) -> None:
        task_set = tmp_path / "task_set.yaml"
        sut_cfg = tmp_path / "sut.yaml"
        task_set.write_text(TASK_SET_YAML, encoding="utf-8")
        sut_cfg.write_text(SUT_YAML, encoding="utf-8")
        inputs = resolve_run_inputs(None, task_set=str(task_set), sut_config=str(sut_cfg))

        import agent_eval.agent.execution_agent as execution_agent_mod
        import agent_eval.execution.channels.base as channels_base

        monkeypatch.setattr(execution_agent_mod, "ExecutionAgent", FakeExecutionAgent)
        monkeypatch.setattr(channels_base, "create_channel", lambda sut: FakeChannel())

        ws = tmp_path / "ws"
        packages = execute_stage(inputs, run_id="r_stages", workspace_root=ws, mode="run")

        assert len(packages) == 1
        manifest_path = ws / "runs" / "r_stages" / "run_manifest.json"
        assert manifest_path.is_file()
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest["mode"] == "run"
        assert manifest["sut"]["name"] == "cw-agent"
        assert len(manifest["packages"]) == 1

    SUT_AUTH_YAML = (
        SUT_YAML
        + """
  auth:
    type: static_token
    credential_ref: NEEDS_KEY
"""
    )

    def test_missing_credentials_fails_fast_no_interaction(self, tmp_path) -> None:
        # execute_stage 层零交互（arch/15 组织约定 5）：即使交互环境也直接 fail fast；
        # 补录发生在命令层进度启动前（_common.ensure_sut_credentials，见 test_cli_run）
        task_set = tmp_path / "task_set.yaml"
        sut_cfg = tmp_path / "sut.yaml"
        task_set.write_text(TASK_SET_YAML, encoding="utf-8")
        sut_cfg.write_text(self.SUT_AUTH_YAML, encoding="utf-8")
        inputs = resolve_run_inputs(None, task_set=str(task_set), sut_config=str(sut_cfg))
        with pytest.raises(SUTAuthError, match="secrets set NEEDS_KEY.token"):
            execute_stage(inputs, run_id="r_fast", workspace_root=tmp_path / "ws", mode="run")


class TestEvaluateStage:
    def test_reuses_existing_run_workspace_and_passes_mode(self, tmp_path, monkeypatch) -> None:
        from agent_eval.storage.workspace import Workspace

        ws = Workspace(tmp_path / "ws")
        ws.create_run("r_reuse")

        calls: dict = {}

        class FakeOrchestrator:
            def __init__(self, workspace=None):
                pass

            def eval_only(self, packages_dir, rule_set_obj, **kwargs):
                calls.update(kwargs, packages_dir=str(packages_dir))
                calls["run_id"] = kwargs.get("run_workspace").run_id
                return "fake-result"

        import agent_eval.orchestrator.orchestrator as orch_mod

        monkeypatch.setattr(orch_mod, "Orchestrator", FakeOrchestrator)

        ctx = JudgeContext(rule_set_obj=object())
        result = evaluate_stage(
            tmp_path / "pkgs", ctx, run=(tmp_path / "ws", "r_reuse"), mode="pipeline"
        )
        assert result == "fake-result"
        assert calls["run_id"] == "r_reuse"
        assert calls["mode"] == "pipeline"
        # run 阶段不建 reports/，evaluate_stage 须补建
        assert (tmp_path / "ws" / "runs" / "r_reuse" / "reports").is_dir()
