"""pipeline 命令输出黄金快照基线。

在抽取 pipeline_core 之前，先从**现行实现**固化四形态 + JSON 形态输出
（exit_code + stdout/stderr 混流）；薄壳化验收门 = 本快照零 diff
（「CLI 外部行为零变化」的机器判定）。

归一化仅抹不稳定项：run_id（时间戳）→ ``<RUN_ID>``、tmp_path → ``<TMP>``；
文案/顺序/表格等语义内容逐字保留。``COLUMNS=200`` 防 rich 换行随路径长度漂移
（macOS 与 CI 的 tmp 路径长度不同）。

再生成（实现变更需更新基线时）::

    AGENT_EVAL_REGEN_GOLDEN=1 uv run pytest tests/unit/test_cli_pipeline_golden.py
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from typer.testing import CliRunner

from agent_eval.cli.main import app

GOLDEN_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "golden" / "pipeline_output"
REGEN = os.environ.get("AGENT_EVAL_REGEN_GOLDEN") == "1"

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
    """真实落盘的假执行器（同 test_cli_pipeline 范式）。"""

    def __init__(self, config, sut_tools=None, extra_tool_servers=None):
        self.config = config
        from agent_eval.agent.executor.sut_tools import SUTToolServer
        from agent_eval.storage.package import ExecutionPackage

        self._sut_tools = SUTToolServer(workspace_dir=self.config.workspace_dir)
        self._package_cls = ExecutionPackage
        self.extra_tool_servers = extra_tool_servers or []

    async def run_task_set(self, task_set, *, run_id: str | None = None, cancel_event=None):
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


def _patch_exec(monkeypatch) -> None:
    import agent_eval.agent.executor.agent as execution_agent_mod
    import agent_eval.execution.channels.base as channels_base

    class FakeChannel:
        async def aclose(self) -> None:
            pass

    monkeypatch.setattr(execution_agent_mod, "ExecutionAgent", FakeExecutionAgent)
    monkeypatch.setattr(channels_base, "create_channel", lambda sut: FakeChannel())


def _patch_eval_ok(monkeypatch, result) -> None:
    """评估段假通过：build_judge_context/evaluate_stage/finalize_eval 三边界。"""
    import agent_eval.cli._stages as stages

    # 上报隔离：仓库 .env 的 AGENT_EVAL_UPLOAD=true 会经 load_dotenv 渗入测试，
    # core 内联的上报段将真发平台（禁联网 + 输出漂移）——显式钉死为关
    monkeypatch.setenv("AGENT_EVAL_UPLOAD", "0")
    monkeypatch.setattr(stages, "build_judge_context", lambda p, strict=False: object())
    monkeypatch.setattr(stages, "evaluate_stage", lambda *a, **kw: result)
    monkeypatch.setattr(stages, "finalize_eval", lambda result, **kw: None)


class _FakeReport:
    metrics = {"edu:reward": 4.5}
    total_samples = 1


class _FakeResult:
    mode = "pipeline"
    # pipeline_core 成功路径触达：samples（SUT 身份回填，空列表跳过）
    samples: list = []
    report = _FakeReport()
    gate = {"mode": "off", "enabled": False, "passed": True}


class _GateFailResult(_FakeResult):
    gate = {
        "mode": "strict",
        "enabled": True,
        "passed": False,
        "failures": ["edu:reward=4.5 < 阈值7.0"],
        "failed_metrics": ["edu:reward"],
    }


def _write_inputs(tmp_path: Path) -> list[str]:
    task_set = tmp_path / "task_set.yaml"
    sut_cfg = tmp_path / "sut.yaml"
    task_set.write_text(TASK_SET_YAML, encoding="utf-8")
    sut_cfg.write_text(SUT_YAML, encoding="utf-8")
    return [
        "--task-set",
        str(task_set),
        "--sut-config",
        str(sut_cfg),
        "--rule-set",
        str(tmp_path / "rs.yaml"),
        "--output-dir",
        str(tmp_path / "ws"),
    ]


def _normalize(output: str, tmp_path: Path) -> str:
    text = output.replace(str(tmp_path), "<TMP>")
    return re.sub(r"\d{8}_\d{6}", "<RUN_ID>", text)


def _assert_golden(name: str, output: str, exit_code: int, tmp_path: Path) -> None:
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    golden = GOLDEN_DIR / f"{name}.golden"
    normalized = f"exit_code={exit_code}\n----\n" + _normalize(output, tmp_path)
    if REGEN:
        golden.write_text(normalized, encoding="utf-8")
        return
    assert golden.is_file(), f"缺黄金快照 {golden}（AGENT_EVAL_REGEN_GOLDEN=1 再生成）"
    assert normalized == golden.read_text(encoding="utf-8"), (
        f"pipeline 输出偏离黄金快照 {golden.name}（CLI 行为零变化验收门）"
    )


def _invoke(args: list[str]):
    return CliRunner(env={"COLUMNS": "200"}).invoke(app, ["pipeline", *args])


def test_golden_success(tmp_path, monkeypatch) -> None:
    """成功形态（normal 档默认）：信息行 → 执行完成 → 任务表 → 流水线完成。"""
    _patch_exec(monkeypatch)
    _patch_eval_ok(monkeypatch, _FakeResult())

    result = _invoke(_write_inputs(tmp_path))
    _assert_golden("success", result.output, result.exit_code, tmp_path)


def test_golden_success_json(tmp_path, monkeypatch) -> None:
    """成功形态（--output-format json）：进度关闭 + 单行机器可读 payload。"""
    _patch_exec(monkeypatch)
    _patch_eval_ok(monkeypatch, _FakeResult())

    result = CliRunner(env={"COLUMNS": "200"}).invoke(
        app, ["--output-format", "json", "pipeline", *_write_inputs(tmp_path)]
    )
    _assert_golden("success_json", result.output, result.exit_code, tmp_path)


def test_golden_execution_failure(tmp_path, monkeypatch) -> None:
    """执行失败形态：exit 1 + 红字「执行失败」。"""
    import agent_eval.agent.executor.agent as execution_agent_mod
    from agent_eval.core.exceptions import AgentEvalError

    class BoomAgent:
        def __init__(self, config, sut_tools=None, extra_tool_servers=None):
            self.config = config

        async def run_task_set(self, task_set, *, run_id=None, cancel_event=None):
            raise AgentEvalError("SUT 不可达")

    import agent_eval.execution.channels.base as channels_base

    class FakeChannel:
        async def aclose(self) -> None:
            pass

    monkeypatch.setattr(execution_agent_mod, "ExecutionAgent", BoomAgent)
    monkeypatch.setattr(channels_base, "create_channel", lambda sut: FakeChannel())

    result = _invoke(_write_inputs(tmp_path))
    _assert_golden("execution_failure", result.output, result.exit_code, tmp_path)


def test_golden_evaluation_failure(tmp_path, monkeypatch) -> None:
    """评估失败形态：exit 1 + 红字「❌ 评估失败」（门禁 0 文案不出现）。"""
    import agent_eval.cli._stages as stages
    from agent_eval.core.exceptions import AgentEvalError

    _patch_exec(monkeypatch)
    monkeypatch.setattr(stages, "build_judge_context", lambda p, strict=False: object())
    monkeypatch.setattr(
        stages,
        "evaluate_stage",
        lambda *a, **kw: (_ for _ in ()).throw(AgentEvalError("judge 不可用")),
    )
    monkeypatch.setattr(stages, "finalize_eval", lambda result, **kw: None)

    result = _invoke(_write_inputs(tmp_path))
    _assert_golden("evaluation_failure", result.output, result.exit_code, tmp_path)


def test_golden_gate_failure(tmp_path, monkeypatch) -> None:
    """门禁未达标形态：exit 3 + 红字「❌ 质量门禁未达标」（上报已完成不回滚）。"""
    _patch_exec(monkeypatch)
    _patch_eval_ok(monkeypatch, _GateFailResult())

    result = _invoke([*_write_inputs(tmp_path), "--gate", "strict"])
    _assert_golden("gate_failure", result.output, result.exit_code, tmp_path)
