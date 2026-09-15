"""CLI `pipeline` 命令测试（Sprint 9 一体化：执行 → 评估 → 上报，单 run_id 贯通）。

范式同 test_cli_run.py：FakeExecutionAgent（patch 源模块属性）+ FakeChannel；
评估段用真实 golden 链路过重（依赖 LLM），此处 patch build_judge_context /
evaluate_stage / finalize_eval 边界，聚焦编排与清单合并语义。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from typer.testing import CliRunner

from agent_eval.cli.main import app

runner = CliRunner()

TASK_SET_YAML = """
id: ts_pipe
name: pipeline 冒烟
tasks:
  - id: t_pipe_1
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
    def __init__(self, config, sut_tools=None, extra_tool_servers=None):
        self.config = config
        from agent_eval.agent.executor.sut_tools import SUTToolServer
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


def _patch_exec(monkeypatch):
    import agent_eval.agent.executor.agent as execution_agent_mod
    import agent_eval.execution.channels.base as channels_base

    class FakeChannel:
        async def aclose(self) -> None:
            pass

    monkeypatch.setattr(execution_agent_mod, "ExecutionAgent", FakeExecutionAgent)
    monkeypatch.setattr(channels_base, "create_channel", lambda sut: FakeChannel())


def test_pipeline_success_single_run_id(tmp_path, monkeypatch) -> None:
    task_set = tmp_path / "task_set.yaml"
    sut_cfg = tmp_path / "sut.yaml"
    task_set.write_text(TASK_SET_YAML, encoding="utf-8")
    sut_cfg.write_text(SUT_YAML, encoding="utf-8")
    _patch_exec(monkeypatch)

    import agent_eval.cli._stages as stages

    eval_calls: dict = {}

    class FakeResult:
        mode = "pipeline"

    def fake_evaluate_stage(packages_dir, judge_ctx, **kwargs):
        eval_calls.update(kwargs)
        eval_calls["packages_dir"] = str(packages_dir)
        return FakeResult()

    monkeypatch.setattr(stages, "build_judge_context", lambda p, strict=False: object())
    monkeypatch.setattr(stages, "evaluate_stage", fake_evaluate_stage)
    monkeypatch.setattr(stages, "finalize_eval", lambda result, **kw: None)

    result = runner.invoke(
        app,
        [
            "pipeline",
            "--task-set",
            str(task_set),
            "--sut-config",
            str(sut_cfg),
            "--rule-set",
            str(tmp_path / "rs.yaml"),
            "--output-dir",
            str(tmp_path / "ws"),
        ],
    )
    assert result.exit_code == 0, result.output

    m = re.search(r"运行 ID: (\S+?)（", result.output)
    assert m, result.output
    run_id = m.group(1)
    run_dir = tmp_path / "ws" / "runs" / run_id

    # 执行产物 + 清单（execute_stage 真实落盘）
    assert (run_dir / "packages" / "t_pipe_1" / "manifest.json").is_file()
    # evaluate_stage 收到同一 run 与 packages 根
    assert Path(eval_calls["packages_dir"]) == run_dir / "packages"
    assert eval_calls["run"][1] == run_id
    assert eval_calls["mode"] == "pipeline"
    assert eval_calls["manifest_extra"]["sut"]["name"] == "cw-agent"

    # manifest_extra 合并断言（清单终态由真实 evaluate_stage 写；此处 fake 未写回，
    # 但执行阶段清单必须已在且 mode=pipeline）
    manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["mode"] == "pipeline"
    assert manifest["packages"], "执行阶段清单须登记包"


def test_pipeline_execution_failure_exits(tmp_path, monkeypatch) -> None:
    task_set = tmp_path / "task_set.yaml"
    sut_cfg = tmp_path / "sut.yaml"
    task_set.write_text(TASK_SET_YAML, encoding="utf-8")
    sut_cfg.write_text(SUT_YAML, encoding="utf-8")

    import agent_eval.agent.executor.agent as execution_agent_mod
    from agent_eval.core.exceptions import AgentEvalError

    class BoomAgent:
        def __init__(self, config, sut_tools=None, extra_tool_servers=None):
            self.config = config

        async def run_task_set(self, task_set, *, run_id=None):
            raise AgentEvalError("SUT 不可达")

    import agent_eval.execution.channels.base as channels_base

    class FakeChannel:
        async def aclose(self) -> None:
            pass

    monkeypatch.setattr(execution_agent_mod, "ExecutionAgent", BoomAgent)
    monkeypatch.setattr(channels_base, "create_channel", lambda sut: FakeChannel())

    result = runner.invoke(
        app,
        [
            "pipeline",
            "--task-set",
            str(task_set),
            "--sut-config",
            str(sut_cfg),
            "--rule-set",
            str(tmp_path / "rs.yaml"),
            "--output-dir",
            str(tmp_path / "ws"),
        ],
    )
    assert result.exit_code == 1
    assert "执行失败" in result.output


def test_pipeline_gate_and_report_formats_passthrough(tmp_path, monkeypatch) -> None:
    """--gate / --report-formats / package_id 正确透传 evaluate_stage。"""
    task_set = tmp_path / "task_set.yaml"
    sut_cfg = tmp_path / "sut.yaml"
    task_set.write_text(TASK_SET_YAML, encoding="utf-8")
    sut_cfg.write_text(SUT_YAML, encoding="utf-8")
    _patch_exec(monkeypatch)

    import agent_eval.cli._stages as stages

    eval_calls: dict = {}

    class FakeResult:
        mode = "pipeline"

    def fake_evaluate_stage(packages_dir, judge_ctx, **kwargs):
        eval_calls.update(kwargs)
        return FakeResult()

    monkeypatch.setattr(stages, "build_judge_context", lambda p, strict=False: object())
    monkeypatch.setattr(stages, "evaluate_stage", fake_evaluate_stage)
    monkeypatch.setattr(stages, "finalize_eval", lambda result, **kw: None)

    result = runner.invoke(
        app,
        [
            "pipeline",
            "--task-set",
            str(task_set),
            "--sut-config",
            str(sut_cfg),
            "--rule-set",
            str(tmp_path / "rs.yaml"),
            "--output-dir",
            str(tmp_path / "ws"),
            "--gate",
            "strict",
            "--report-formats",
            "junit,txt",
        ],
    )
    assert result.exit_code == 0, result.output
    assert eval_calls["gate"] == "strict"
    assert eval_calls["report_formats"] == ["junit", "txt"]
    assert eval_calls["package_id"] == ""  # 无 --package（显式路径模式）


def test_pipeline_report_formats_invalid_value(tmp_path, monkeypatch) -> None:
    """非法 --report-formats 值 → usage 错误（click 约定 exit 2），不进入执行。"""
    task_set = tmp_path / "task_set.yaml"
    sut_cfg = tmp_path / "sut.yaml"
    task_set.write_text(TASK_SET_YAML, encoding="utf-8")
    sut_cfg.write_text(SUT_YAML, encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "pipeline",
            "--task-set",
            str(task_set),
            "--sut-config",
            str(sut_cfg),
            "--report-formats",
            "html",
        ],
    )
    assert result.exit_code == 2
    assert "不支持的报告格式" in result.output


def test_pipeline_gate_failure_exits_3(tmp_path, monkeypatch) -> None:
    """门禁未达标 → exit 3（Jenkins UNSTABLE），报告/上报已完成不回滚。"""
    task_set = tmp_path / "task_set.yaml"
    sut_cfg = tmp_path / "sut.yaml"
    task_set.write_text(TASK_SET_YAML, encoding="utf-8")
    sut_cfg.write_text(SUT_YAML, encoding="utf-8")
    _patch_exec(monkeypatch)

    import agent_eval.cli._stages as stages

    finalized: list = []

    class FakeResult:
        mode = "pipeline"
        gate = {
            "mode": "strict",
            "enabled": True,
            "passed": False,
            "failures": ["edu:reward=4.5 < 阈值7.0"],
            "failed_metrics": ["edu:reward"],
        }

    monkeypatch.setattr(stages, "build_judge_context", lambda p, strict=False: object())
    monkeypatch.setattr(stages, "evaluate_stage", lambda *a, **kw: FakeResult())
    monkeypatch.setattr(stages, "finalize_eval", lambda result, **kw: finalized.append(result))

    result = runner.invoke(
        app,
        [
            "pipeline",
            "--task-set",
            str(task_set),
            "--sut-config",
            str(sut_cfg),
            "--rule-set",
            str(tmp_path / "rs.yaml"),
            "--output-dir",
            str(tmp_path / "ws"),
            "--gate",
            "strict",
        ],
    )
    assert result.exit_code == 3, result.output
    assert "质量门禁未达标" in result.output
    assert finalized, "门禁失败不阻断 finalize（上报已完成）"


def test_pipeline_json_payload_uses_report_fr4(tmp_path, monkeypatch) -> None:
    """FR-4：--output-format json 终态渲染走 result.report，不再 AttributeError。"""
    task_set = tmp_path / "task_set.yaml"
    sut_cfg = tmp_path / "sut.yaml"
    task_set.write_text(TASK_SET_YAML, encoding="utf-8")
    sut_cfg.write_text(SUT_YAML, encoding="utf-8")
    _patch_exec(monkeypatch)

    import agent_eval.cli._stages as stages

    class FakeReport:
        metrics = {"edu:reward": 4.5}
        total_samples = 1

    class FakeResult:
        mode = "pipeline"
        report = FakeReport()
        gate = {"mode": "off", "enabled": False, "passed": True}

    monkeypatch.setattr(stages, "build_judge_context", lambda p, strict=False: object())
    monkeypatch.setattr(stages, "evaluate_stage", lambda *a, **kw: FakeResult())
    monkeypatch.setattr(stages, "finalize_eval", lambda result, **kw: None)

    result = runner.invoke(
        app,
        [
            "--output-format",
            "json",
            "pipeline",
            "--task-set",
            str(task_set),
            "--sut-config",
            str(sut_cfg),
            "--rule-set",
            str(tmp_path / "rs.yaml"),
            "--output-dir",
            str(tmp_path / "ws"),
        ],
    )
    assert result.exit_code == 0, result.output
    # emit_json 输出单行 JSON；CliRunner 混流时人读行（stderr）也在 output 里，按行提取
    m = re.search(r'^\{"run_id".*$', result.output, re.MULTILINE)
    assert m, result.output
    payload = json.loads(m.group(0))
    assert payload["mode"] == "pipeline"
    assert payload["metrics"] == {"edu:reward": 4.5}
    assert payload["total_samples"] == 1
