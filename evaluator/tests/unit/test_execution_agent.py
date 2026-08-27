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
                    # 对齐真 langchain 派发：on_llm_end 必带 run_id 关键字
                    callback.on_llm_end(
                        {"usage_metadata": {"input_tokens": 10, "output_tokens": 5}},
                        run_id="fake-run-id",
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


def _fix_run_id(monkeypatch, run_id: str = "r_fix") -> None:
    """固定 run_id（W7：预写包须落在 runs/{run_id}/packages/ 下）。"""
    monkeypatch.setattr(execution_agent_mod, "generate_run_id", lambda: run_id)


def _pkg_root(tmp_path: Path, run_id: str = "r_fix") -> Path:
    return tmp_path / "runs" / run_id / "packages"


def test_run_task_success_with_agent_package(tmp_path, monkeypatch) -> None:
    agent = _agent(tmp_path)
    graph = _install_fakes(monkeypatch, FakeGraph(result={"messages": _messages()}))
    _fix_run_id(monkeypatch)
    # 模拟 Agent 会话内已调用 write_package（成功包；W7 落 runs/{run_id}/packages/）
    agent.sut_tools.workspace_dir = _pkg_root(tmp_path)
    asyncio.run(
        agent.sut_tools.write_package(
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

    # ainvoke 配置：recursion_limit=max_turns*2、双回调；
    # 不注入 thread_id（无 checkpointer，单任务单发无恢复语义，v4.6.3）
    _, config = graph.invocations[0]
    assert "configurable" not in config
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
    _fix_run_id(monkeypatch)
    _install_fakes(monkeypatch, FakeGraph(result={"messages": _messages()}, fire_callbacks=True))
    agent = _agent(tmp_path)
    package = asyncio.run(agent.run_task(_task()))

    # Agent 未写包 → 兜底失败包 + task/trace/metrics 补齐
    assert package.manifest.status == "failed"
    pkg_dir = _pkg_root(tmp_path) / "task_1"
    assert (pkg_dir / "task.json").exists()
    assert (pkg_dir / "trace.json").exists()
    metrics = _read_json(pkg_dir / "metrics.json")
    assert metrics["tool_calls"] == 1

    # 回调触发的 token 计量进入汇总日志（一次 on_llm_end: 10+5）
    summary_file = next((tmp_path / "runs").glob("*/agent_logs/agent_summary.jsonl"))
    summary = json.loads(summary_file.read_text(encoding="utf-8").splitlines()[0])
    assert summary["tokens_used"] == 15
    assert summary["tool_calls"] == 0


def test_run_task_recursion_error_becomes_timeout(tmp_path, monkeypatch) -> None:
    _fix_run_id(monkeypatch)
    _install_fakes(monkeypatch, FakeGraph(error=GraphRecursionError("limit")))
    agent = _agent(tmp_path)
    with pytest.raises(AgentTimeoutError):
        asyncio.run(agent.run_task(_task()))
    manifest = _read_json(_pkg_root(tmp_path) / "task_1" / "manifest.json")
    assert manifest["status"] == "failed"


def test_run_task_budget_exceeded_preserves_partial_package(tmp_path, monkeypatch) -> None:
    _install_fakes(monkeypatch, FakeGraph(error=BudgetExceededError("over budget")))
    agent = _agent(tmp_path)
    _fix_run_id(monkeypatch)
    # 预置 Agent 已写的成功包（部分结果）→ 异常路径不得覆盖
    agent.sut_tools.workspace_dir = _pkg_root(tmp_path)
    asyncio.run(agent.sut_tools.write_package(task_id="task_1", success=True))
    with pytest.raises(BudgetExceededError):
        asyncio.run(agent.run_task(_task()))
    manifest = _read_json(_pkg_root(tmp_path) / "task_1" / "manifest.json")
    assert manifest["status"] == "success"


def test_run_task_generic_error_wrapped(tmp_path, monkeypatch) -> None:
    _fix_run_id(monkeypatch)
    _install_fakes(monkeypatch, FakeGraph(error=RuntimeError("checkpointer down")))
    agent = _agent(tmp_path)
    with pytest.raises(AgentError, match="会话异常中断"):
        asyncio.run(agent.run_task(_task()))


def test_run_task_without_deepagents_friendly_error(tmp_path, monkeypatch) -> None:
    _fix_run_id(monkeypatch)
    # 未安装伪 deepagents 且真实环境未安装 → 友好提示 + 失败包
    monkeypatch.setitem(sys.modules, "deepagents", None)
    agent = _agent(tmp_path)
    with pytest.raises(AgentError, match="agent-eval\\[agent\\]"):
        asyncio.run(agent.run_task(_task()))
    # W7：包归位 runs/{run_id}/packages/
    assert (_pkg_root(tmp_path) / "task_1" / "manifest.json").exists()


def test_run_task_set_shares_run_id(tmp_path, monkeypatch) -> None:
    _install_fakes(monkeypatch, FakeGraph(result={"messages": _messages()}))
    agent = _agent(tmp_path)
    task_set = TaskSet(id="ts", name="批量", tasks=[_task("t_a"), _task("t_b")])
    run_id, packages = asyncio.run(agent.run_task_set(task_set))
    assert [p.manifest.task_id for p in packages] == ["t_a", "t_b"]
    run_dir = tmp_path / "runs" / run_id
    assert run_id
    assert run_dir.is_dir()  # 共享 run_id
    # W7：执行包归位 runs/{run_id}/packages/{task_id}（不再写 workspace 根）
    assert (run_dir / "packages" / "t_a" / "manifest.json").exists()
    assert (run_dir / "packages" / "t_b" / "manifest.json").exists()
    assert not (tmp_path / "t_a").exists()
    log_names = sorted(p.name for p in (run_dir / "agent_logs").glob("agent_t*.jsonl"))
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


def test_prompts_sourced_from_yaml_asset(tmp_path) -> None:
    """提示词由 YAML 资产承载（不 hardcode）：结构完整 + 变量替换正确。"""
    from agent_eval.agent.execution_agent import _load_prompts

    prompts = _load_prompts()
    assert set(prompts["task_prompt"]) == {
        "header",
        "input",
        "forward",
        "expected",
        "constraints",
        "directory_mode",
        "footer",
    }

    agent = _agent(tmp_path)
    system_prompt = agent._build_system_prompt()
    # YAML 模板特征句 + 运行时变量替换（工具清单 / 轮次与重试上限）
    assert "## 输出规范" in system_prompt
    assert "scan_directory" in system_prompt
    assert f"{agent.config.max_turns} 轮内完成" in system_prompt
    assert f"最多重试 {agent.config.max_retries} 次" in system_prompt


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


def test_trace_backfills_sut_last_run_text(tmp_path, monkeypatch) -> None:
    _fix_run_id(monkeypatch)
    """trace 回填 SUT 最终回答（工具注册表记录的 last_run，v4.6.4）。"""
    graph = _install_fakes(monkeypatch, FakeGraph(result={"messages": _messages()}))
    agent = _agent(tmp_path)
    agent.sut_tools.workspace_dir = _pkg_root(tmp_path)
    asyncio.run(agent.sut_tools.write_package(task_id="task_1", success=True))
    agent = _agent(tmp_path)
    assert graph is not None

    class _StubSutServer:
        last_run = {
            "status": "success",
            "thread_id": "th-1",
            "run_id": "r-1",
            "text": "一元一次方程的标准形式是 ax+b=0…",
        }

        def to_langchain_tools(self) -> list:
            return []

        def describe_tools(self) -> str:
            return "stub"

    agent = ExecutionAgent(
        AgentConfig(workspace_dir=tmp_path, max_turns=7), extra_tool_servers=[_StubSutServer()]
    )
    # 模拟 Agent 会话内已写成功包（run_task 不再兜底 failed）
    asyncio.run(agent.sut_tools.write_package(task_id="task_1", success=True))
    package = asyncio.run(agent.run_task(_task()))
    assert package.manifest.status == "success"
    trace = _read_json(_pkg_root(tmp_path) / "task_1" / "trace.json")
    assert trace["response"]["sut"]["text"].startswith("一元一次方程")
    # 过程指标（Sprint 9 v6.0）：trace.response 携带真轮次与执行耗时
    assert "turns" in trace["response"]
    assert "duration_ms" in trace["response"]
    assert trace["response"]["sut"]["thread_id"] == "th-1"
    assert trace["response"]["messages"] == len(_messages())


def test_trace_without_sut_run_keeps_counts_only(tmp_path, monkeypatch) -> None:
    _fix_run_id(monkeypatch)
    """无 last_run 注册表（如目录模式）时 trace 保持计数形态，不造 sut 键。"""
    _install_fakes(monkeypatch, FakeGraph(result={"messages": _messages()}))
    agent = _agent(tmp_path)
    asyncio.run(agent.run_task(_task()))
    trace = _read_json(_pkg_root(tmp_path) / "task_1" / "trace.json")
    assert "sut" not in trace["response"]
    assert trace["response"]["tool_calls"] >= 0


def test_answer_file_materialized_from_last_run(tmp_path, monkeypatch) -> None:
    _fix_run_id(monkeypatch)
    """SUT 回答物化为 output/answer.md（对话型任务，评估器按文件收集文本）。"""
    _install_fakes(monkeypatch, FakeGraph(result={"messages": _messages()}))

    class _StubSutServer:
        last_run = {"status": "success", "thread_id": "t", "run_id": "r", "text": "回答正文"}

        def to_langchain_tools(self) -> list:
            return []

        def describe_tools(self) -> str:
            return "stub"

    agent = ExecutionAgent(
        AgentConfig(workspace_dir=tmp_path, max_turns=7), extra_tool_servers=[_StubSutServer()]
    )
    asyncio.run(agent.sut_tools.write_package(task_id="task_1", success=True))
    asyncio.run(agent.run_task(_task()))
    answer = _pkg_root(tmp_path) / "task_1" / "output" / "answer.md"
    assert answer.exists() and answer.read_text(encoding="utf-8") == "回答正文"


def test_answer_file_not_duplicated_when_output_has_files(tmp_path, monkeypatch) -> None:
    """SUT 已有产物文件时不物化（不覆盖真实产物）。"""
    _install_fakes(monkeypatch, FakeGraph(result={"messages": _messages()}))

    class _StubSutServer:
        last_run = {"status": "success", "thread_id": "t", "run_id": "r", "text": "回答"}

        def to_langchain_tools(self) -> list:
            return []

        def describe_tools(self) -> str:
            return "stub"

    agent = ExecutionAgent(
        AgentConfig(workspace_dir=tmp_path, max_turns=7), extra_tool_servers=[_StubSutServer()]
    )
    asyncio.run(agent.sut_tools.write_package(task_id="task_1", success=True))
    output_dir = _pkg_root(tmp_path) / "task_1" / "output"
    output_dir.mkdir(parents=True)
    (output_dir / "artifact.html").write_text("<html/>", encoding="utf-8")
    asyncio.run(agent.run_task(_task()))
    assert not (output_dir / "answer.md").exists()


def test_task_prompt_includes_deterministic_forward_section(tmp_path) -> None:
    """forward 段提供确定性的纯文本转发内容（修复 agent_run input 格式不一致）。"""
    agent = _agent(tmp_path)
    task = _task("task_1")
    task.input = {"instruction": "请解释什么是勾股定理", "intent": "math_qa"}
    prompt = agent._build_task_prompt(task)
    assert "## 转发指令" in prompt
    assert "请解释什么是勾股定理" in prompt
    assert "不是 JSON" in prompt  # 明确告知纯文本
    # intent 的值不混入转发指令文本（应放 metadata；模板自身提及 intent 字样属正常指导语）
    forward_section = prompt.split("## 转发指令")[1].split("## ")[0]
    assert "math_qa" not in forward_section  # intent 值不出现
    # 转发的纯文本行以 instruction 内容开头（agent_run input 就是这段文字）
    assert "请解释什么是勾股定理" in forward_section


def test_extract_instruction_variants() -> None:
    """_extract_instruction 覆盖 dict/str/缺失键三种形态。"""
    from agent_eval.execution.models import Task as TaskModel

    # dict 有 instruction 键
    t = TaskModel(id="t1", input={"instruction": "你好", "intent": "greeting"})
    assert ExecutionAgent._extract_instruction(t) == "你好"

    # dict 无 instruction 键 → 取第一个字符串值
    t2 = TaskModel(id="t2", input={"prompt": "测试", "meta": "info"})
    assert ExecutionAgent._extract_instruction(t2) == "测试"

    # 纯字符串 input
    t3 = TaskModel(id="t3", input={"instruction": "直接文本"})
    assert ExecutionAgent._extract_instruction(t3) == "直接文本"


def test_trace_merge_preserves_llm_sut_run_and_adds_agent_stats(tmp_path, monkeypatch) -> None:
    """merge 语义（Sprint 9 v6.0）：LLM write_package 已写 SUT-run 形态 trace/metrics 时，
    Agent 过程统计以 setdefault 补充，不覆盖其字段。"""
    import asyncio

    _fix_run_id(monkeypatch)
    graph = _install_fakes(monkeypatch, FakeGraph(result={"messages": _messages()}))
    assert graph is not None
    agent = _agent(tmp_path)
    agent.sut_tools.workspace_dir = _pkg_root(tmp_path)
    # 模拟 LLM 已通过 write_package 工具写入 SUT-run 形态（真实 pipeline 运行实测形态）
    asyncio.run(
        agent.sut_tools.write_package(
            task_id="task_1",
            success=True,
            trace={"run_id": "sut-r", "thread_id": "th", "sut_response": "答", "turns_used": 1},
            metrics={"response_length": 920, "status": "success"},
        )
    )
    package = asyncio.run(agent.run_task(_task()))
    assert package.manifest.status == "success"
    trace = _read_json(_pkg_root(tmp_path) / "task_1" / "trace.json")
    # LLM 字段保留
    assert trace["run_id"] == "sut-r"
    assert trace["sut_response"] == "答"
    # Agent 过程统计补充（response.* + started/finished）
    assert "turns" in trace["response"]
    assert "tool_calls" in trace["response"]
    assert "duration_ms" in trace["response"]
    metrics = _read_json(_pkg_root(tmp_path) / "task_1" / "metrics.json")
    assert metrics["response_length"] == 920  # LLM 字段保留
    assert "total_duration_ms" in metrics  # 过程统计补充
