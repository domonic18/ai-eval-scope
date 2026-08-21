"""ExecutionAgent 单元测试（DeepAgents 底座，arch/03 §三 v4.6）——伪 deepagents/langchain 全离线。"""

from __future__ import annotations

import asyncio
import json
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_eval.agent import execution_agent as execution_agent_mod
from agent_eval.agent.execution_agent import ExecutionAgent
from agent_eval.core.exceptions import AgentError, AgentTimeoutError, BudgetExceededError
from agent_eval.execution.models import AgentConfig, Task, TaskSet


class GraphRecursionError(Exception):
    """伪 langgraph.errors.GraphRecursionError（按类名识别）。"""


class FakeGraph:
    """伪 DeepAgents CompiledStateGraph：记录 ainvoke 入参，可控返回/异常。"""

    def __init__(self, result=None, error: Exception | None = None, fire_callbacks=False):
        self.result = result
        self.error = error
        self.fire_callbacks = fire_callbacks
        self.invocations: list[tuple[dict, dict | None]] = []

    async def ainvoke(self, payload: dict, config: dict | None = None):
        self.invocations.append((payload, config))
        if self.fire_callbacks and config:
            for callback in config.get("callbacks", []):
                if hasattr(callback, "on_llm_end"):
                    callback.on_llm_end(
                        {"usage_metadata": {"input_tokens": 10, "output_tokens": 5}}
                    )
        if self.error is not None:
            raise self.error
        return self.result


def _install_fakes(monkeypatch, graph: FakeGraph) -> FakeGraph:
    """注入伪 deepagents / langchain_core / build_chat_model。"""
    fake_deepagents = types.ModuleType("deepagents")
    fake_deepagents.create_deep_agent = lambda **kwargs: graph
    monkeypatch.setitem(sys.modules, "deepagents", fake_deepagents)

    class FakeStructuredTool:
        @staticmethod
        def from_function(*, coroutine=None, name=None, description=None):
            return {"name": name}

    fake_pkg = types.ModuleType("langchain_core")
    fake_tools = types.ModuleType("langchain_core.tools")
    fake_tools.StructuredTool = FakeStructuredTool
    fake_pkg.tools = fake_tools
    monkeypatch.setitem(sys.modules, "langchain_core", fake_pkg)
    monkeypatch.setitem(sys.modules, "langchain_core.tools", fake_tools)

    monkeypatch.setattr(
        execution_agent_mod,
        "build_chat_model",
        lambda *a, **k: SimpleNamespace(fake="chat-model"),
    )
    return graph


def _agent(tmp_path: Path) -> ExecutionAgent:
    return ExecutionAgent(AgentConfig(workspace_dir=tmp_path, max_turns=7))


def _task(task_id: str = "task_1") -> Task:
    return Task(id=task_id, input={"subject": "数学"}, constraints={"min_documents": 2})


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_run_task_success_with_agent_package(tmp_path, monkeypatch) -> None:
    agent = _agent(tmp_path)
    graph = _install_fakes(monkeypatch, FakeGraph(result={"messages": _messages()}))
    # 模拟 Agent 会话内已调用 write_package（成功包）
    asyncio.run(
        agent.sut_tools.write_package(
            workspace_dir=str(tmp_path),
            task_id="task_1",
            success=True,
            trace={"request": {}, "response": {}, "started_at": "t", "finished_at": "t"},
            metrics={"tool_calls": 1},
        )
    )
    package = asyncio.run(agent.run_task(_task()))

    assert package.manifest.task_id == "task_1"
    assert package.manifest.status == "success"
    assert package.task_data["input"] == {"subject": "数学"}  # 缺省补写 task.json

    # ainvoke 配置：thread_id=task.id、recursion_limit=max_turns*2、双回调
    _, config = graph.invocations[0]
    assert config["configurable"]["thread_id"] == "task_1"
    assert config["recursion_limit"] == 14
    assert len(config["callbacks"]) == 2

    # 结构化日志落盘
    log_file = next((tmp_path / "runs").glob("*/agent_logs/agent_task_1.jsonl"))
    events = [
        json.loads(line)["event"]
        for line in log_file.read_text(encoding="utf-8").splitlines()
        if line
    ]
    assert events[0] == "agent_start"
    assert events[-1] == "agent_end"


def _messages() -> list[SimpleNamespace]:
    return [
        SimpleNamespace(type="human"),
        SimpleNamespace(
            type="ai",
            tool_calls=[{"name": "write_package"}],
            usage_metadata={"input_tokens": 10, "output_tokens": 5},
        ),
        SimpleNamespace(type="tool"),
        SimpleNamespace(type="ai", tool_calls=[]),
    ]


def test_run_task_fallback_package_when_agent_skips_write(tmp_path, monkeypatch) -> None:
    _install_fakes(monkeypatch, FakeGraph(result={"messages": _messages()}, fire_callbacks=True))
    agent = _agent(tmp_path)
    package = asyncio.run(agent.run_task(_task()))

    # Agent 未写包 → 兜底失败包 + task/trace/metrics 补齐
    assert package.manifest.status == "failed"
    assert (tmp_path / "task_1" / "task.json").exists()
    assert (tmp_path / "task_1" / "trace.json").exists()
    metrics = _read_json(tmp_path / "task_1" / "metrics.json")
    assert metrics["tool_calls"] == 1

    # 回调触发的 token 计量进入汇总日志（一次 on_llm_end: 10+5）
    summary_file = next((tmp_path / "runs").glob("*/agent_logs/agent_summary.jsonl"))
    summary = json.loads(summary_file.read_text(encoding="utf-8").splitlines()[0])
    assert summary["tokens_used"] == 15
    assert summary["tool_calls"] == 0


def test_run_task_recursion_error_becomes_timeout(tmp_path, monkeypatch) -> None:
    _install_fakes(monkeypatch, FakeGraph(error=GraphRecursionError("limit")))
    agent = _agent(tmp_path)
    with pytest.raises(AgentTimeoutError):
        asyncio.run(agent.run_task(_task()))
    manifest = _read_json(tmp_path / "task_1" / "manifest.json")
    assert manifest["status"] == "failed"


def test_run_task_budget_exceeded_preserves_partial_package(tmp_path, monkeypatch) -> None:
    _install_fakes(monkeypatch, FakeGraph(error=BudgetExceededError("over budget")))
    agent = _agent(tmp_path)
    # 预置 Agent 已写的成功包（部分结果）→ 异常路径不得覆盖
    asyncio.run(
        agent.sut_tools.write_package(workspace_dir=str(tmp_path), task_id="task_1", success=True)
    )
    with pytest.raises(BudgetExceededError):
        asyncio.run(agent.run_task(_task()))
    manifest = _read_json(tmp_path / "task_1" / "manifest.json")
    assert manifest["status"] == "success"


def test_run_task_generic_error_wrapped(tmp_path, monkeypatch) -> None:
    _install_fakes(monkeypatch, FakeGraph(error=RuntimeError("checkpointer down")))
    agent = _agent(tmp_path)
    with pytest.raises(AgentError, match="会话异常中断"):
        asyncio.run(agent.run_task(_task()))


def test_run_task_without_deepagents_friendly_error(tmp_path, monkeypatch) -> None:
    # 未安装伪 deepagents 且真实环境未安装 → 友好提示 + 失败包
    monkeypatch.setitem(sys.modules, "deepagents", None)
    agent = _agent(tmp_path)
    with pytest.raises(AgentError, match="agent-eval\\[agent\\]"):
        asyncio.run(agent.run_task(_task()))
    assert (tmp_path / "task_1" / "manifest.json").exists()


def test_run_task_set_shares_run_id(tmp_path, monkeypatch) -> None:
    _install_fakes(monkeypatch, FakeGraph(result={"messages": _messages()}))
    agent = _agent(tmp_path)
    task_set = TaskSet(id="ts", name="批量", tasks=[_task("t_a"), _task("t_b")])
    packages = asyncio.run(agent.run_task_set(task_set))
    assert [p.manifest.task_id for p in packages] == ["t_a", "t_b"]
    run_dirs = list((tmp_path / "runs").iterdir())
    assert len(run_dirs) == 1  # 共享 run_id
    log_names = sorted(p.name for p in (run_dirs[0] / "agent_logs").glob("agent_t*.jsonl"))
    assert log_names == ["agent_t_a.jsonl", "agent_t_b.jsonl"]


def test_prompt_contents(tmp_path) -> None:
    agent = _agent(tmp_path)
    system_prompt = agent._build_system_prompt()
    assert "invoke_http_sut" in system_prompt
    assert "write_package" in system_prompt

    task = Task(
        id="dir_task",
        input={"subject": "物理"},
        input_mode="directory",
        directory_path="/data/产出",
        file_patterns=["*.html"],
    )
    task_prompt = agent._build_task_prompt(task)
    assert "## 任务 ID: dir_task" in task_prompt
    assert "目录模式" in task_prompt
    assert "/data/产出" in task_prompt
    assert str(tmp_path / "dir_task") in task_prompt


def test_graph_built_once_and_reused(tmp_path, monkeypatch) -> None:
    graph = _install_fakes(monkeypatch, FakeGraph(result={"messages": _messages()}))
    agent = _agent(tmp_path)
    asyncio.run(agent.run_task(_task("t_x")))
    asyncio.run(agent.run_task(_task("t_x")))
    # create_deep_agent 只构建一次，图实例复用
    assert agent._graph is graph
    assert len(graph.invocations) == 2


def test_task_prompt_expected_block(tmp_path) -> None:
    agent = _agent(tmp_path)
    task = Task(id="e1", input={}, expected={"知识点": ["浮力"]})
    prompt = agent._build_task_prompt(task)
    assert "预期结果" in prompt
    assert "浮力" in prompt
