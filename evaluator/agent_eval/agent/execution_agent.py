"""ExecutionAgent — 基于 DeepAgents（Python）的执行 Agent（arch/03 §三 v4.6）。

端到端驱动评测执行流程：理解任务、调用 SUT Tools、处理错误、收集结果、
生成 ExecutionPackage。底座为 deepagents 的 create_deep_agent（惰性导入，
[agent] optional extra）；模型经 build_chat_model 从 llm_config 双协议桥接；
BudgetGuard/SessionLogCallback 以 LangGraph 回调注入（预算/结构化日志）；
会话状态经 WorkspaceCheckpointer 落盘（推理-执行-状态分离）。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agent_eval.agent.callbacks import BudgetGuard, SessionLogCallback
from agent_eval.agent.hooks import SessionLogger
from agent_eval.agent.model_bridge import build_chat_model
from agent_eval.agent.session import AgentSession, WorkspaceCheckpointer
from agent_eval.agent.sut_tools import SUTToolServer
from agent_eval.core.exceptions import (
    AgentError,
    AgentTimeoutError,
    BudgetExceededError,
)
from agent_eval.execution.models import AgentConfig, ProcessMetrics, Task, TaskSet
from agent_eval.storage.package import ExecutionPackage, generate_run_id


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _is_recursion_error(error: BaseException) -> bool:
    """识别 LangGraph GraphRecursionError（按类名，避免硬依赖 langgraph）。"""
    return type(error).__name__ == "GraphRecursionError"


class ExecutionAgent:
    """基于 DeepAgents 的执行 Agent，端到端驱动评测执行流程。

    - 模型：llm_config.yaml provider → build_chat_model() 构造 ChatModel（双协议，模型无关）
    - 工具：SUT Tools 经 LangChain Tool 显式绑定（白名单），未绑定工具不可用
    - 预算：BudgetGuard 回调（on_llm_end 累计 token/成本，超限抛 BudgetExceededError）
    - 状态：WorkspaceCheckpointer 会话状态落盘（崩溃可恢复，thread_id=task.id）
    """

    def __init__(
        self,
        config: AgentConfig,
        sut_tools: SUTToolServer | None = None,
        *,
        extra_tool_servers: list[Any] | None = None,
    ) -> None:
        """初始化 ExecutionAgent（DeepAgents 图惰性装配，导入本类无需 [agent] extra）。

        Args:
            config: Agent 配置（轮次/预算/llm_provider/workspace 等）。
            sut_tools: SUT 工具注册表；缺省按 config.sut_tools_config 构建。
            extra_tool_servers: 追加工具注册表（如 AgentProtocolToolServer，
                arch/03 §4.0.6 语义工具面），与 SUT Tools 一同显式绑定。
        """
        self.config = config
        self.sut_tools = sut_tools or SUTToolServer(config.sut_tools_config)
        self.tool_servers: list[Any] = [self.sut_tools, *(extra_tool_servers or [])]
        self._graph: Any = None

    # ─── 对外入口 ───

    async def run_task_set(self, task_set: TaskSet) -> list[ExecutionPackage]:
        """批量执行任务集（共享 run_id），返回执行包列表。"""
        run_id = generate_run_id()
        return [await self.run_task(task, run_id=run_id) for task in task_set.tasks]

    async def run_task(self, task: Task, *, run_id: str | None = None) -> ExecutionPackage:
        """执行单个任务，返回 ExecutionPackage。

        Raises:
            AgentTimeoutError: 超过轮次限制（已写入含部分结果的执行包）。
            BudgetExceededError: 超过 max_budget_usd（已写入错误执行包）。
            AgentError: DeepAgents/LangGraph 运行时异常（已写入错误执行包）。
        """
        run_id = run_id or generate_run_id()
        workspace = Path(self.config.workspace_dir)
        package_dir = workspace / task.id
        log_dir = workspace / "runs" / run_id / "agent_logs"

        logger = SessionLogger(run_id, task.id, log_dir=log_dir)
        guard = BudgetGuard(self.config.max_budget_usd)
        logger.log_start(task.input, task.constraints)

        try:
            graph = self._ensure_graph()
            result = await graph.ainvoke(
                {"messages": [{"role": "user", "content": self._build_task_prompt(task)}]},
                config={
                    "configurable": {"thread_id": task.id},
                    "recursion_limit": self.config.max_turns * 2,
                    "callbacks": [SessionLogCallback(logger), guard],
                },
            )
        except (BudgetExceededError, AgentTimeoutError, AgentError) as e:
            await self._abort(logger, guard, task, package_dir, e)
            raise
        except Exception as e:
            error: AgentError
            if _is_recursion_error(e):
                error = AgentTimeoutError(
                    f"Agent 执行超过轮次限制（max_turns={self.config.max_turns}）"
                )
            else:
                error = AgentError(f"Agent 会话异常中断: {e}")
            await self._abort(logger, guard, task, package_dir, error)
            raise error from e

        session = AgentSession.from_messages(result.get("messages", []))
        session.started_at = logger.started_at or _now_iso()
        session.finished_at = _now_iso()
        package = await self._build_package(session, task, package_dir)
        logger.log_end(
            cost_usd=guard.spent_usd,
            tokens_used=guard.total_tokens,
            turns_used=session.turns_used,
        )
        logger.close()
        return package

    # ─── DeepAgents 图装配 ───

    def _ensure_graph(self) -> Any:
        """惰性装配 DeepAgents 图（首次 run_task 时构建并复用）。"""
        if self._graph is None:
            self._graph = self._build_graph()
        return self._graph

    def _build_graph(self) -> Any:
        """构建 DeepAgents 图：模型桥接 + 工具显式绑定 + 状态落盘。"""
        try:
            from deepagents import create_deep_agent
        except ImportError:
            raise AgentError(
                "ExecutionAgent 需要 deepagents（DeepAgents 底座，见 arch/03 §3.2）。"
                "请执行: pip install 'agent-eval[agent]'",
                details={"missing_module": "deepagents"},
            ) from None
        tools = [tool for server in self.tool_servers for tool in server.to_langchain_tools()]
        return create_deep_agent(
            model=build_chat_model(self.config.llm_provider, self.config.model),
            tools=tools,
            system_prompt=self._build_system_prompt(),
            checkpointer=WorkspaceCheckpointer(self.config.workspace_dir),
        )

    # ─── Prompt 构建（arch/03 §3.3/§3.4） ───

    def _describe_all_tools(self) -> str:
        """汇总全部工具注册表（SUT Tools + 追加注册表）的描述清单。"""
        return "\n".join(server.describe_tools() for server in self.tool_servers)

    def _build_system_prompt(self) -> str:
        """System Prompt：角色职责 + 可用工具 + 执行规则 + 输出规范。"""
        return f"""你是一个评测执行 Agent（ExecutionAgent），负责驱动被测系统（SUT）执行任务并收集结果。

## 你的职责
1. 理解任务描述，确定需要调用的 SUT 交互方式
2. 构造正确的请求参数，调用合适的 SUT Tool
3. 检查响应是否成功，如遇错误则智能重试或降级
4. 收集执行结果文件，生成目录清单（如适用）
5. 任务结束时调用 write_package 写入执行包

## 可用工具
{self._describe_all_tools()}

## 执行规则
- 每个任务必须在 {self.config.max_turns} 轮内完成
- 遇到超时或服务错误时，最多重试 {self.config.max_retries} 次，仍失败则降级或终止
- 必须在任务结束时调用 write_package 写入执行包
- 如果 SUT 交互失败且无法恢复，调用 write_package(success=false, error=...) 写入错误信息

## 输出规范
- 所有输出文件必须写入指定 workspace 目录
- 目录模式任务需先调用 scan_directory 扫描目录结构
"""

    def _build_task_prompt(self, task: Task) -> str:
        """Task Prompt：任务输入/预期/约束 + 目录模式说明 + 写包指令。"""
        package_dir = Path(self.config.workspace_dir) / task.id
        parts = [
            f"## 任务 ID: {task.id}",
            "## 任务输入",
            json.dumps(task.input, ensure_ascii=False, indent=2),
        ]
        if task.expected:
            parts.append(f"## 预期结果\n{json.dumps(task.expected, ensure_ascii=False, indent=2)}")
        if task.constraints:
            parts.append(
                f"## 约束条件\n{json.dumps(task.constraints, ensure_ascii=False, indent=2)}"
            )
        if task.input_mode == "directory" and task.directory_path:
            parts.extend(
                [
                    "## 目录模式",
                    f"- 目录路径: {task.directory_path}",
                    f"- 文件匹配模式: {task.file_patterns}",
                    "请先调用 scan_directory 扫描目录结构，然后收集结果文件。",
                ]
            )
        parts.append(f"请执行上述任务，并在完成后调用 write_package 将执行包写入 {package_dir}。")
        return "\n\n".join(parts)

    # ─── ExecutionPackage 构建 ───

    async def _build_package(
        self,
        session: AgentSession,
        task: Task,
        package_dir: Path,
    ) -> ExecutionPackage:
        """从 Agent 会话构建 ExecutionPackage。

        Agent 已调用 write_package 时直接加载其产物；否则写入兜底失败包
        （status=failed，error=未写包说明），再补齐 task/trace/metrics。
        """
        if not (package_dir / "manifest.json").exists():
            await self.sut_tools.write_package(
                workspace_dir=str(self.config.workspace_dir),
                task_id=task.id,
                success=False,
                error="Agent 未调用 write_package，已由 ExecutionAgent 兜底写包",
            )
        self._ensure_task_file(task, package_dir)
        self._ensure_trace_file(session, package_dir)
        self._ensure_metrics_file(session, package_dir)
        return ExecutionPackage.load(package_dir)

    async def _abort(
        self,
        logger: SessionLogger,
        guard: BudgetGuard,
        task: Task,
        package_dir: Path,
        error: BaseException,
    ) -> None:
        """异常路径统一收尾：日志 + 错误执行包（保留 Agent 已写的部分结果）。"""
        logger.log_error(type(error).__name__, str(error))
        if not (package_dir / "manifest.json").exists():
            await self.sut_tools.write_package(
                workspace_dir=str(self.config.workspace_dir),
                task_id=task.id,
                success=False,
                error=str(error),
            )
        logger.log_end(cost_usd=guard.spent_usd, tokens_used=guard.total_tokens)
        logger.close()

    def _ensure_task_file(self, task: Task, package_dir: Path) -> None:
        task_file = package_dir / "task.json"
        if not task_file.exists():
            task_file.write_text(task.model_dump_json(indent=2), encoding="utf-8")

    def _ensure_trace_file(self, session: AgentSession, package_dir: Path) -> None:
        trace_file = package_dir / "trace.json"
        if trace_file.exists():
            return
        trace = {
            "request": {"executor": "ExecutionAgent", "llm_provider": self.config.llm_provider},
            "response": {
                "messages": len(session.messages),
                "tool_calls": session.tool_call_count,
            },
            "started_at": session.started_at,
            "finished_at": session.finished_at or _now_iso(),
            "error": None,
        }
        trace_file.write_text(json.dumps(trace, ensure_ascii=False, indent=2), encoding="utf-8")

    def _ensure_metrics_file(self, session: AgentSession, package_dir: Path) -> None:
        metrics_file = package_dir / "metrics.json"
        if metrics_file.exists():
            return
        duration_ms = 0.0
        try:
            start = datetime.fromisoformat(session.started_at)
            end = datetime.fromisoformat(session.finished_at or _now_iso())
            duration_ms = (end - start).total_seconds() * 1000
        except ValueError:
            pass
        metrics = ProcessMetrics(
            total_duration_ms=duration_ms,
            steps=len(session.messages),
            tool_calls=session.tool_call_count,
        )
        metrics_file.write_text(
            json.dumps(metrics.model_dump(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
