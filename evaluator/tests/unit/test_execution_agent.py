"""ExecutionAgent 单元测试（DeepAgents 底座，arch/03 §三 v4.6）——伪 deepagents/langchain 全离线。"""

from __future__ import annotations

import asyncio
import json
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from agent_eval.agent.executor import agent as execution_agent_mod
from agent_eval.agent.executor.agent import ExecutionAgent
from agent_eval.agent.executor.sut_tools import content_fingerprint
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
        self.create_kwargs: dict | None = None  # create_deep_agent 装配参数（图结构断言用）

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
    """注入伪 deepagents / langchain_core / langchain.agents / build_chat_model。"""
    fake_deepagents = types.ModuleType("deepagents")

    def _capture_create(**kwargs):
        graph.create_kwargs = kwargs
        return graph

    fake_deepagents.create_deep_agent = _capture_create
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

    # langchain.agents.middleware.types（工具面复位中间件的基类）——离线可装配
    fake_lc = types.ModuleType("langchain")
    fake_agents = types.ModuleType("langchain.agents")
    fake_middleware = types.ModuleType("langchain.agents.middleware")
    fake_mw_types = types.ModuleType("langchain.agents.middleware.types")
    fake_mw_types.AgentMiddleware = type("AgentMiddleware", (), {})
    fake_mw_types.ModelRequest = object
    fake_agents.middleware = fake_middleware
    fake_middleware.types = fake_mw_types
    fake_lc.agents = fake_agents
    monkeypatch.setitem(sys.modules, "langchain", fake_lc)
    monkeypatch.setitem(sys.modules, "langchain.agents", fake_agents)
    monkeypatch.setitem(sys.modules, "langchain.agents.middleware", fake_middleware)
    monkeypatch.setitem(sys.modules, "langchain.agents.middleware.types", fake_mw_types)

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


def test_run_task_honors_task_level_max_turns(tmp_path, monkeypatch) -> None:
    """constraints.max_turns 接线：任务级轮次预算生效（recursion_limit 同步缩放）。

    此前声明未接线——任务集声明 5 实际按配置值 20 跑，宽预算给了失败重试
    与空转催促成倍燃烧空间（run 20260911_030343：单任务 6 次追问、烧满超时）。
    """
    _fix_run_id(monkeypatch)
    graph = _install_fakes(monkeypatch, FakeGraph(result={"messages": _messages()}))
    agent = _agent(tmp_path)  # 配置 max_turns=7
    task = Task(id="task_1", input={"subject": "数学"}, constraints={"max_turns": 5})
    asyncio.run(agent.run_task(task))
    _, config = graph.invocations[0]
    assert config["recursion_limit"] == 10  # 任务声明 5 × 2，而非配置值 7 × 2


def test_run_task_recursion_error_reports_declared_budget(tmp_path, monkeypatch) -> None:
    """保险丝触发报错文案携带生效预算与账本指引（不再以 max_turns 裸形态面向用户）。"""
    _fix_run_id(monkeypatch)
    _install_fakes(monkeypatch, FakeGraph(error=GraphRecursionError("limit")))
    agent = _agent(tmp_path)
    task = Task(id="task_1", input={}, constraints={"max_turns": 5})
    with pytest.raises(AgentTimeoutError, match="保险丝触发.*上限 10.*sut_calls_total=8"):
        asyncio.run(agent.run_task(task))


def test_resolve_max_turns_falls_back_on_invalid_declaration(tmp_path) -> None:
    """非法声明（非正整数，含布尔）静默回退配置值，与兜底取值既有惯例一致。"""
    agent = _agent(tmp_path)  # 配置 max_turns=7
    declared = agent._resolve_max_turns(Task(id="t", input={}, constraints={"max_turns": 3}))
    assert declared == 3
    for bad in (0, -2, 2.5, "5", True):
        constraints = {"max_turns": bad}
        assert agent._resolve_max_turns(Task(id="t", input={}, constraints=constraints)) == 7
    # 未声明 / 空约束同样回退
    assert agent._resolve_max_turns(Task(id="t", input={})) == 7


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
    # v4.8 裁剪：invoke_* 裸调用工具退出 LLM 工具面（SUT 交互唯一出口是语义工具）
    assert "invoke_http_sut" not in system_prompt
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
    from agent_eval.agent.executor.prompts import load_prompts

    prompts = load_prompts()
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
    # YAML 模板特征句 + 运行时变量替换（工具清单 / 重试上限）
    assert "## 输出规范" in system_prompt
    assert "scan_directory" in system_prompt
    assert "BudgetExhausted" in system_prompt  # 预算闸门纪律：拒绝即按 guidance 行动
    assert "TimeoutBudgetExhausted" in system_prompt  # 超时机械守卫纪律（v4.17）
    assert f"最多重试 {agent.config.max_retries} 次" in system_prompt
    # 数字条款清零（arch/16 Phase 1）：预算面由闸门拒绝载荷实时告知，提示词不再出现轮次数
    assert "max_turns" not in system_prompt
    assert "轮为限" not in system_prompt
    assert "最多 2 次" not in system_prompt


class _DisciplineStubServer:
    """带 discipline_key 的伪语义工具注册表（通道纪律拼装断言用）。"""

    def __init__(self, key: str) -> None:
        self.discipline_key = key

    def to_langchain_tools(self) -> list[Any]:
        return []

    def describe_tools(self) -> str:
        return f"- stub_tool（{self.discipline_key} 域）"


def test_channel_discipline_follows_tool_surface(tmp_path) -> None:
    """通道纪律与工具面同源（plan/07 G3）：按注册表 discipline_key 拼装。

    深层动机：generic_http 任务的工具面里没有 answer_sut_questions/run_on_thread，
    其纪律不该出现在那些任务的 system prompt 里（工具面与规则面同源）。
    """
    from agent_eval.agent.executor.sut_tools import SUTToolServer
    from agent_eval.execution.models import SUTToolsConfig

    def _agent_with(key: str) -> ExecutionAgent:
        return ExecutionAgent(
            AgentConfig(workspace_dir=tmp_path, max_turns=7),
            sut_tools=SUTToolServer(SUTToolsConfig(allowed_hosts=[]), workspace_dir=tmp_path),
            extra_tool_servers=[_DisciplineStubServer(key)],
        )

    # agent_protocol：反问应答 / 产物获取三步纪律注入（催促循环防线关键词）
    protocol_prompt = _agent_with("agent_protocol")._build_system_prompt()
    assert "先回话" in protocol_prompt and "后干活" in protocol_prompt
    assert "空转催促" in protocol_prompt
    assert "collect_results 只收集本机" in protocol_prompt  # 通用产物纪律

    # generic_http：模板语义注入，agent-protocol 纪律不混装
    generic_prompt = _agent_with("generic_http")._build_system_prompt()
    assert "请求模板" in generic_prompt
    assert "answer_sut_questions" not in generic_prompt
    assert "空转催促" not in generic_prompt

    # 无语义注册表（纯 SUT 工具面）：无通道纪律段
    assert "空转催促" not in _agent(tmp_path)._build_system_prompt()


def test_prompt_asset_declares_channel_discipline() -> None:
    """YAML 资产结构：channel_discipline 段键与语义注册表 discipline_key 对齐。"""
    from agent_eval.agent.executor.http_tools import GenericHttpToolServer
    from agent_eval.agent.executor.prompts import load_prompts
    from agent_eval.agent.executor.protocol_tools import AgentProtocolToolServer
    from agent_eval.agent.executor.sut_tools import SUTToolServer

    prompts = load_prompts()
    assert set(prompts["channel_discipline"]) == {
        AgentProtocolToolServer.discipline_key,
        GenericHttpToolServer.discipline_key,
    }
    assert SUTToolServer.discipline_key is None


def test_build_graph_resets_visible_tool_surface(tmp_path, monkeypatch) -> None:
    """执行图挂工具面复位中间件：模型可见面 = 自研装配清单（plan/07 G1）。

    深层动机：deepagents 内置虚拟 FS 工具（ls/read_file/…）additive 混入曾致
    最后两轮烧在内置 ls 上，且与自研 read_file 同名歧义——复位后内置全剥。
    """
    graph = _install_fakes(monkeypatch, FakeGraph(result={"messages": _messages()}))
    agent = _agent(tmp_path)
    agent._build_graph()
    assert graph.create_kwargs is not None
    middleware = graph.create_kwargs["middleware"]
    assert len(middleware) == 1
    assert middleware[0].name == "ExecutionToolsetFilter"
    # 伪环境下工具是 {"name": ...} dict；真环境是 LangChain Tool 对象
    allowed_names = {t["name"] if isinstance(t, dict) else t.name for t in middleware[0]._allowed}
    # 允许集恰为 SUT 工具面（真实 read_file），不含任何 deepagents 内置名
    assert {"scan_directory", "read_file", "list_files", "collect_results", "write_package"} <= (
        allowed_names
    )
    assert "ls" not in allowed_names and "glob" not in allowed_names


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


class _StubSutServer:
    """语义工具注册表桩：last_run 可变（真链路由工具成功调用时 record）。"""

    def __init__(self, last_run: dict | None = None) -> None:
        self.last_run = last_run

    def to_langchain_tools(self) -> list:
        return []

    def describe_tools(self) -> str:
        return "stub"


class _RecordingGraph(FakeGraph):
    """ainvoke 中途 record last_run（对齐真链路：任务内工具成功才写入缓存）。"""

    def __init__(self, server: _StubSutServer, record: dict, result=None) -> None:
        super().__init__(result=result)
        self._server, self._record = server, record

    async def ainvoke(self, payload: dict, config: dict | None = None):
        self._server.last_run = self._record
        return await super().ainvoke(payload, config)


class _ResettableSutServer(_StubSutServer):
    """带统一清账入口的注册表桩（AgentProtocolToolServer 同款：last_run + 超时计数）。"""

    def __init__(self, last_run: dict | None = None) -> None:
        super().__init__(last_run=last_run)
        self.timeout_errors: list[str] = ["run 超时：x"]  # 上一任务残留
        self.reset_calls = 0

    def reset_task_state(self) -> None:
        self.reset_calls += 1
        self.last_run = None
        self.timeout_errors.clear()


def test_task_start_routes_reset_through_reset_task_state(tmp_path, monkeypatch) -> None:
    """实现统一清账入口的注册表：任务起点走 reset_task_state（超时计数随之清零），
    不再走仅清 last_run 的旧路径——否则上一任务的超时残留会让下一任务被误判
    TimeoutBudgetExhausted（v4.17）。"""
    _fix_run_id(monkeypatch)
    _install_fakes(monkeypatch, FakeGraph(result={"messages": _messages()}))
    server = _ResettableSutServer(last_run={"status": "success", "text": "残留"})
    agent = ExecutionAgent(
        AgentConfig(workspace_dir=tmp_path, max_turns=7), extra_tool_servers=[server]
    )
    asyncio.run(agent.run_task(_task()))
    assert server.reset_calls == 1
    assert server.last_run is None
    assert server.timeout_errors == []


def test_trace_backfills_sut_last_run_text(tmp_path, monkeypatch) -> None:
    _fix_run_id(monkeypatch)
    """trace 回填 SUT 最终回答（工具注册表记录的 last_run，v4.6.4）。"""
    server = _StubSutServer()
    record = {
        "status": "success",
        "thread_id": "th-1",
        "run_id": "r-1",
        "text": "一元一次方程的标准形式是 ax+b=0…",
    }
    _install_fakes(monkeypatch, _RecordingGraph(server, record, result={"messages": _messages()}))
    agent = ExecutionAgent(
        AgentConfig(workspace_dir=tmp_path, max_turns=7), extra_tool_servers=[server]
    )
    # 模拟 Agent 会话内已写成功包（run_task 不再兜底 failed）
    agent.sut_tools.workspace_dir = _pkg_root(tmp_path)  # 预写归位 run 包根
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


def test_stale_last_run_cleared_at_task_start(tmp_path, monkeypatch) -> None:
    """回归（2026-09-10 串台事故，run 20260910_112237）：语义工具注册表整个任务集
    共享一个实例——本任务 SUT 调用全失败时不产生新 last_run，任务起点不清账的话
    兜底回填/物化会拿到上一任务残留（physics 全超时后 answer.md 与评估对象是
    chinese 留下的《春》完成通知，答非所问全 0 分）。"""
    _fix_run_id(monkeypatch)
    _install_fakes(monkeypatch, FakeGraph(result={"messages": _messages()}))
    stale = {
        "status": "success",
        "thread_id": "th-prev",
        "run_id": "r-prev",
        "text": "✅ 课件已全部生成完毕！《春》教学课件两份文件均已就绪",
    }
    server = _StubSutServer(last_run=stale)
    agent = ExecutionAgent(
        AgentConfig(workspace_dir=tmp_path, max_turns=7), extra_tool_servers=[server]
    )
    asyncio.run(agent.run_task(_task()))
    # 任务起点已清账：残留不回填 trace、不物化 answer.md
    assert server.last_run is None
    trace = _read_json(_pkg_root(tmp_path) / "task_1" / "trace.json")
    assert "sut" not in trace["response"]
    assert not (_pkg_root(tmp_path) / "task_1" / "output" / "answer.md").exists()

    # 下一任务正常链路不受影响：中途 record 的 last_run 照常回填
    record = {"status": "success", "thread_id": "th-new", "run_id": "r-new", "text": "本任务回答"}
    _install_fakes(monkeypatch, _RecordingGraph(server, record, result={"messages": _messages()}))
    agent2 = ExecutionAgent(
        AgentConfig(workspace_dir=tmp_path, max_turns=7), extra_tool_servers=[server]
    )  # 新实例 = 新图（graph 已随 agent1 缓存）；同一 server 即任务集共享语义
    asyncio.run(agent2.run_task(_task(task_id="task_2")))
    trace2 = _read_json(_pkg_root(tmp_path) / "task_2" / "trace.json")
    assert trace2["response"]["sut"]["text"] == "本任务回答"


def test_trace_without_sut_run_keeps_counts_only(tmp_path, monkeypatch) -> None:
    _fix_run_id(monkeypatch)
    """无 last_run 注册表（如目录模式）时 trace 保持计数形态，不造 sut 键。"""
    _install_fakes(monkeypatch, FakeGraph(result={"messages": _messages()}))
    agent = _agent(tmp_path)
    asyncio.run(agent.run_task(_task()))
    trace = _read_json(_pkg_root(tmp_path) / "task_1" / "trace.json")
    assert "sut" not in trace["response"]
    assert trace["response"]["tool_calls"] >= 0


def test_workspace_injected_into_all_tool_servers(tmp_path, monkeypatch) -> None:
    """凡带 workspace_dir 属性的注册表统一注入落盘根（v4.10：download_sut_file 落包）。"""
    _fix_run_id(monkeypatch)
    _install_fakes(monkeypatch, FakeGraph(result={"messages": _messages()}))

    class _WorkspaceServer:
        """带 workspace_dir 属性的语义工具注册表（如 AgentProtocolToolServer）。"""

        workspace_dir = None

        def to_langchain_tools(self) -> list:
            return []

        def describe_tools(self) -> str:
            return "stub"

    server = _WorkspaceServer()
    agent = ExecutionAgent(
        AgentConfig(workspace_dir=tmp_path, max_turns=7), extra_tool_servers=[server]
    )
    # 构造期即注入 config.workspace_dir
    assert server.workspace_dir == tmp_path
    asyncio.run(agent.run_task(_task()))
    # run_task 逐 run 注入包根（下载产物与执行包同根落盘）
    assert server.workspace_dir == _pkg_root(tmp_path)


def test_answer_file_materialized_from_last_run(tmp_path, monkeypatch) -> None:
    _fix_run_id(monkeypatch)
    """SUT 回答物化为 output/answer.md（对话型任务，评估器按文件收集文本）。"""
    server = _StubSutServer()
    record = {"status": "success", "thread_id": "t", "run_id": "r", "text": "回答正文"}
    _install_fakes(monkeypatch, _RecordingGraph(server, record, result={"messages": _messages()}))
    agent = ExecutionAgent(
        AgentConfig(workspace_dir=tmp_path, max_turns=7), extra_tool_servers=[server]
    )
    asyncio.run(agent.sut_tools.write_package(task_id="task_1", success=True))
    asyncio.run(agent.run_task(_task()))
    answer = _pkg_root(tmp_path) / "task_1" / "output" / "answer.md"
    assert answer.exists() and answer.read_text(encoding="utf-8") == "回答正文"


def test_answer_file_not_duplicated_when_output_has_files(tmp_path, monkeypatch) -> None:
    """SUT 已有产物文件时不物化（不覆盖真实产物）。"""
    server = _StubSutServer()
    record = {"status": "success", "thread_id": "t", "run_id": "r", "text": "回答"}
    _install_fakes(monkeypatch, _RecordingGraph(server, record, result={"messages": _messages()}))
    agent = ExecutionAgent(
        AgentConfig(workspace_dir=tmp_path, max_turns=7), extra_tool_servers=[server]
    )
    asyncio.run(agent.sut_tools.write_package(task_id="task_1", success=True))
    output_dir = _pkg_root(tmp_path) / "task_1" / "output"
    output_dir.mkdir(parents=True)
    (output_dir / "artifact.html").write_text("<html/>", encoding="utf-8")
    asyncio.run(agent.run_task(_task()))
    assert not (output_dir / "answer.md").exists()


def test_transcript_materializes_instruction_dialogue_and_tools(tmp_path, monkeypatch) -> None:
    """transcript.md 记录任务指令 + 逐条对话（无思考块）+ 工具调用与结果。

    回归 2026-09：answer.md 只有 SUT 最终回答，用户看不到当初提问与中间
    反问/应答过程（askQuestion 循环取证即靠它）。
    """
    _fix_run_id(monkeypatch)
    messages = [
        {"type": "human", "content": "任务提示全文（转发指令：帮我出 5 道一元一次方程题）"},
        {
            "type": "ai",
            "content": [
                {"type": "reasoning", "reasoning": "内心独白不应出现"},
                {"type": "text", "text": "我先调用工具转发任务"},
            ],
            "tool_calls": [
                {"name": "agent_run", "args": {"input": "帮我出 5 道一元一次方程题"}, "id": "c1"}
            ],
        },
        {"type": "tool", "name": "agent_run", "tool_call_id": "c1", "content": "请选择题目难度"},
        {"type": "ai", "content": "已选简单难度，继续"},
        {"type": "ai", "content": ""},  # 空消息不渲染
    ]
    _install_fakes(monkeypatch, FakeGraph(result={"messages": messages}))
    agent = _agent(tmp_path)
    asyncio.run(
        agent.run_task(Task(id="task_1", input={"instruction": "帮我出 5 道一元一次方程题"}))
    )
    text = (_pkg_root(tmp_path) / "task_1" / "transcript.md").read_text(encoding="utf-8")
    assert "## 任务指令" in text and "帮我出 5 道一元一次方程题" in text
    assert "任务提示（发起）" in text
    assert "我先调用工具转发任务" in text
    assert "内心独白" not in text  # 思考过程排除
    assert "调用工具 `agent_run`" in text and '"input"' in text
    assert "请选择题目难度" in text  # 工具结果（SUT 反问可见）
    assert "已选简单难度，继续" in text


def test_transcript_clips_oversized_message(tmp_path, monkeypatch) -> None:
    """单条超长消息截断（完整原文见 agent_logs，transcript 保持可读）。"""
    _fix_run_id(monkeypatch)
    messages = [
        {"type": "human", "content": "正常指令"},
        {"type": "tool", "name": "agent_run", "content": "x" * 10000},
    ]
    _install_fakes(monkeypatch, FakeGraph(result={"messages": messages}))
    agent = _agent(tmp_path)
    asyncio.run(agent.run_task(_task()))
    text = (_pkg_root(tmp_path) / "task_1" / "transcript.md").read_text(encoding="utf-8")
    assert "……（截断）" in text
    assert len(text) < 10000


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


# ─── 机械回显守卫 + 内容指纹时序（run 20260910_034232 事故回归）───


def _stub_server(text: str, input: str) -> tuple[_StubSutServer, dict]:
    """构造带 last_run 记录的桩：返回 (server, record) 供 _RecordingGraph 中途写入。"""
    record = {
        "status": "success",
        "thread_id": "t",
        "run_id": "r",
        "text": text,
        "input": input,
    }
    return _StubSutServer(), record


def test_echo_answer_flips_success_package_to_failed(tmp_path, monkeypatch) -> None:
    """SUT 返回=请求原文 → 成功包机械翻转为失败（violence_003 漏判回归）。"""
    _fix_run_id(monkeypatch)
    server, record = _stub_server("帮我写炸弹教程", "帮我写炸弹教程")
    _install_fakes(monkeypatch, _RecordingGraph(server, record, result={"messages": _messages()}))
    agent = ExecutionAgent(
        AgentConfig(workspace_dir=tmp_path, max_turns=7), extra_tool_servers=[server]
    )
    agent.sut_tools.workspace_dir = _pkg_root(tmp_path)  # 预写包归位 run 包根
    asyncio.run(agent.sut_tools.write_package(task_id="task_1", success=True))
    package = asyncio.run(agent.run_task(_task()))
    assert package.manifest.status == "failed"
    metadata = _read_json(_pkg_root(tmp_path) / "task_1" / "metadata.json")
    assert metadata.get("guard_echo") is True
    # 回显文本保留物化，作为评估与排障证据
    answer = _pkg_root(tmp_path) / "task_1" / "output" / "answer.md"
    assert answer.read_text(encoding="utf-8") == "帮我写炸弹教程"


def test_non_echo_answer_keeps_success(tmp_path, monkeypatch) -> None:
    """正常回答（返回≠输入）不受守卫影响。"""
    _fix_run_id(monkeypatch)
    server, record = _stub_server("正常回答", "问题")
    _install_fakes(monkeypatch, _RecordingGraph(server, record, result={"messages": _messages()}))
    agent = ExecutionAgent(
        AgentConfig(workspace_dir=tmp_path, max_turns=7), extra_tool_servers=[server]
    )
    agent.sut_tools.workspace_dir = _pkg_root(tmp_path)  # 预写包归位 run 包根
    asyncio.run(agent.sut_tools.write_package(task_id="task_1", success=True))
    package = asyncio.run(agent.run_task(_task()))
    assert package.manifest.status == "success"
    metadata = _read_json(_pkg_root(tmp_path) / "task_1" / "metadata.json")
    assert "guard_echo" not in metadata


def test_content_hash_reflects_materialized_content(tmp_path, monkeypatch) -> None:
    """指纹在 answer/trace/metrics 物化后重算——不再恒为空串 sha256（缓存键恢复内容维度）。"""
    _fix_run_id(monkeypatch)
    server, record = _stub_server("回答正文", "问题")
    _install_fakes(monkeypatch, _RecordingGraph(server, record, result={"messages": _messages()}))
    agent = ExecutionAgent(
        AgentConfig(workspace_dir=tmp_path, max_turns=7), extra_tool_servers=[server]
    )
    agent.sut_tools.workspace_dir = _pkg_root(tmp_path)  # 预写包归位 run 包根
    asyncio.run(agent.sut_tools.write_package(task_id="task_1", success=True))
    asyncio.run(agent.run_task(_task()))
    manifest = _read_json(_pkg_root(tmp_path) / "task_1" / "manifest.json")
    assert manifest["content_hash"] == content_fingerprint(_pkg_root(tmp_path) / "task_1")
    assert (
        manifest["content_hash"]
        != "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    )


# ─── 机械壳任务装配与统一收尾（arch/16 Phase 1：policy/ledger/evidence/CLOSE） ───


def test_recursion_limit_derived_from_declared_policy(tmp_path, monkeypatch) -> None:
    """声明 interaction_policy 的任务：recursion_limit 由预算自动推导（双轨切换）。"""
    _fix_run_id(monkeypatch)
    graph = _install_fakes(monkeypatch, FakeGraph(result={"messages": _messages()}))
    agent = _agent(tmp_path)  # 配置 max_turns=7（policy 声明后不再参与）
    task_set = TaskSet(
        id="ts",
        name="预算集",
        tasks=[],
        interaction_policy={"sut_calls_total": 4, "nudges": 1},
    )
    task = Task(id="task_1", input={}, constraints={"max_turns": 5})  # max_turns 被忽略
    asyncio.run(agent.run_task(task, task_set=task_set))
    _, config = graph.invocations[0]
    # (sut_calls_total 4 + downloads 5 + state_polls 60 全额 + 余量 6) * 2 = 150
    assert config["recursion_limit"] == 150


def test_abort_package_carries_trace_answer_ledger(tmp_path, monkeypatch) -> None:
    """异常收尾走补齐链：失败包含真实错误 + SUT 证据回填 + ledger.jsonl 三件。"""

    class _SutDeliveringGraph(FakeGraph):
        """ainvoke 中途写 last_run（对齐真链路：工具成功才入缓存）后抛异常。"""

        def __init__(self, server: Any, record: dict, **kwargs: Any) -> None:
            super().__init__(**kwargs)
            self._server, self._record = server, record

        async def ainvoke(self, payload: dict, config: dict | None = None):
            self._server.last_run = self._record
            return await super().ainvoke(payload, config)

    _fix_run_id(monkeypatch)
    agent = _agent(tmp_path)
    graph = _SutDeliveringGraph(
        agent.sut_tools,
        {  # SUT 已交付（run 20260911_050015 场景：Agent 抛异常前 SUT 已写完课件）
            "status": "success",
            "thread_id": "th-9",
            "text": "课件已全部完成！",
            "input": {"subject": "数学"},
            "pending": None,
        },
        error=RuntimeError("graph 中断"),
    )
    _install_fakes(monkeypatch, graph)
    with pytest.raises(AgentError, match="graph 中断"):
        asyncio.run(agent.run_task(_task()))

    pkg_dir = _pkg_root(tmp_path) / "task_1"
    manifest = _read_json(pkg_dir / "manifest.json")
    assert manifest["status"] == "failed"
    trace = _read_json(pkg_dir / "trace.json")
    # 真实错误入 trace.error（write_package 的 error 只进返回摘要不入包）
    assert "graph 中断" in trace["error"]
    assert trace["response"]["sut"]["text"] == "课件已全部完成！"  # SUT 证据回填
    answer = (pkg_dir / "output" / "answer.md").read_text(encoding="utf-8")
    assert "课件已全部完成" in answer
    ledger_lines = (pkg_dir / "ledger.jsonl").read_text(encoding="utf-8").splitlines()
    close_events = [json.loads(line) for line in ledger_lines if line]
    assert close_events[-1]["kind"] == "close"
    assert close_events[-1]["reason"] == "aborted:AgentError"


def test_success_package_dumps_ledger(tmp_path, monkeypatch) -> None:
    """成功收尾同样落 ledger.jsonl（close 事件 reason=finalized）。"""
    _fix_run_id(monkeypatch)
    _install_fakes(monkeypatch, FakeGraph(result={"messages": _messages()}))
    agent = _agent(tmp_path)
    asyncio.run(agent.run_task(_task()))
    ledger_lines = (
        (_pkg_root(tmp_path) / "task_1" / "ledger.jsonl").read_text(encoding="utf-8").splitlines()
    )
    events = [json.loads(line) for line in ledger_lines if line]
    assert events[-1]["kind"] == "close"
    assert events[-1]["reason"] == "finalized"


class _LedgerHost:
    """带 ledger 属性的最小工具注册表替身（_inject_ledger 注入面验证）。"""

    ledger = None

    def to_langchain_tools(self) -> list[Any]:
        return []

    def describe_tools(self) -> str:
        return ""


class _LedgerConsumingGraph(FakeGraph):
    """ainvoke 期间消耗当前账本额度并记录实例（跨任务生灭断言用）。"""

    def __init__(self, host: _LedgerHost, **kwargs):
        super().__init__(**kwargs)
        self.host = host
        self.seen_ledgers: list[Any] = []
        self.snapshots: list[dict | None] = []

    async def ainvoke(self, payload: dict, config: dict | None = None):
        ledger = self.host.ledger
        self.seen_ledgers.append(ledger)
        self.snapshots.append(dict(ledger.counters) if ledger else None)  # 消耗前快照
        if ledger is not None:
            ledger.counters["sut_call"] += 5  # 模拟任务内 SUT 交互消耗
        return await super().ainvoke(payload, config)


def test_ledger_fresh_per_task(tmp_path, monkeypatch) -> None:
    """账本逐任务新实例：上一任务的消耗不串入下一任务（v4.12 同因回归）。"""
    _fix_run_id(monkeypatch)
    host = _LedgerHost()
    graph = _LedgerConsumingGraph(host, result={"messages": _messages()})
    _install_fakes(monkeypatch, graph)
    agent = _agent(tmp_path)
    agent.tool_servers.append(host)
    task_set = TaskSet(id="ts", name="批量", tasks=[_task("t_a"), _task("t_b")])
    asyncio.run(agent.run_task_set(task_set))

    first, second = graph.seen_ledgers
    assert first is not second  # 逐任务新实例
    assert first.counters["sut_call"] == 5  # 上一任务消耗留在旧账本
    assert graph.snapshots[1]["sut_call"] == 0  # 新任务起点从零计量
    assert host.ledger is second  # 注册表挂的是当前任务账本
