"""ExecutionAgent — 基于 DeepAgents（Python）的执行 Agent。

端到端驱动评测执行流程：理解任务、调用 SUT Tools、处理错误、收集结果、
生成 ExecutionPackage。底座为 deepagents 的 create_deep_agent（惰性导入，
[agent] optional extra）；模型经 build_chat_model 从角色注册表双协议桥接；
BudgetGuard/SessionLogCallback 以 LangGraph 回调注入（预算/结构化日志）。

本模块只保留装配与执行循环；prompt 构建见 executor/prompts.py，
包物化与机械守卫见 executor/package_writer.py，transcript 渲染见
executor/transcript.py（plan/07 G4 拆分）。
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog

from agent_eval.agent.core.callbacks import BudgetGuard, SessionLogCallback
from agent_eval.agent.core.model_bridge import build_chat_model
from agent_eval.agent.core.session import AgentSession
from agent_eval.agent.core.session_log import SessionLogger
from agent_eval.agent.core.tool_filter import build_toolset_filter
from agent_eval.agent.executor.package_writer import (
    ensure_failure_package,
    finalize_execution_package,
)
from agent_eval.agent.executor.prompts import (
    build_system_prompt,
    build_task_prompt,
    extract_instruction,
)
from agent_eval.agent.executor.sut_tools import SUTToolServer
from agent_eval.core.exceptions import (
    AgentError,
    AgentTimeoutError,
    BudgetExceededError,
)
from agent_eval.execution.models import AgentConfig, Task, TaskSet
from agent_eval.storage.package import ExecutionPackage, generate_run_id


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _is_recursion_error(error: BaseException) -> bool:
    """识别 LangGraph GraphRecursionError（按类名，避免硬依赖 langgraph）。"""
    return type(error).__name__ == "GraphRecursionError"


class ExecutionAgent:
    """基于 DeepAgents 的执行 Agent，端到端驱动评测执行流程。

    - 模型：LLM 角色注册表 → build_chat_model() 构造 ChatModel（双协议，模型无关）
    - 工具：SUT Tools 经 LangChain Tool 显式绑定（白名单），未绑定工具不可用
    - 预算：BudgetGuard 回调（on_llm_end 累计 token/成本，超限抛 BudgetExceededError）
    - 状态：单任务单发 ainvoke，不接 checkpointer（见 _build_graph 说明）
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
            config: Agent 配置（轮次/预算/llm_role/workspace 等）。
            sut_tools: SUT 工具注册表；缺省按 config.sut_tools_config 构建。
            extra_tool_servers: 追加工具注册表（如 AgentProtocolToolServer
                语义工具面），与 SUT Tools 一同显式绑定。
        """
        self.config = config
        self.sut_tools = sut_tools or SUTToolServer(
            config.sut_tools_config, workspace_dir=config.workspace_dir
        )
        self.tool_servers: list[Any] = [self.sut_tools, *(extra_tool_servers or [])]
        # 落盘根统一注入：凡有 workspace_dir 属性的注册表（SUTToolServer /
        # AgentProtocolToolServer 等）同以 config.workspace_dir 为根——
        # write_package/collect_results/download_sut_file 的目的地不交给 LLM 决定
        self._inject_workspace(Path(config.workspace_dir))
        self._graph: Any = None

    def _inject_workspace(self, workspace_dir: Path) -> None:
        """向所有带 workspace_dir 属性的工具注册表注入落盘根。"""
        for server in self.tool_servers:
            if hasattr(server, "workspace_dir"):
                server.workspace_dir = workspace_dir

    # ─── 对外入口 ───

    async def run_task_set(
        self, task_set: TaskSet, *, run_id: str | None = None
    ) -> tuple[str, list[ExecutionPackage]]:
        """批量执行任务集（共享 run_id），返回 (run_id, 执行包列表)。

        run_id 可由调用方（CLI）注入——用于运行清单登记与外部关联。
        """
        run_id = run_id or generate_run_id()
        packages = []
        total = len(task_set.tasks)
        for idx, task in enumerate(task_set.tasks, start=1):
            # 逐任务进度上终端（stderr）：执行域只有一根转轮，单任务数十分钟时
            # 表现为「卡住不动」（SUT 反问循环实测 2026-09）——开始/结束都要可见
            structlog.get_logger("executor").info(
                "任务开始",
                task_id=task.id,
                progress=f"{idx}/{total}",
            )
            started = time.monotonic()
            package = await self.run_task(task, run_id=run_id)
            structlog.get_logger("executor").info(
                "任务结束",
                task_id=task.id,
                progress=f"{idx}/{total}",
                status=package.manifest.status,
                elapsed_s=round(time.monotonic() - started, 1),
            )
            packages.append(package)
        return run_id, packages

    async def run_task(self, task: Task, *, run_id: str | None = None) -> ExecutionPackage:
        """执行单个任务，返回 ExecutionPackage。

        Raises:
            AgentTimeoutError: 超过轮次限制（已写入含部分结果的执行包）。
            BudgetExceededError: 超过 max_budget_usd（已写入错误执行包）。
            AgentError: DeepAgents/LangGraph 运行时异常（已写入错误执行包）。
        """
        run_id = run_id or generate_run_id()
        workspace = Path(self.config.workspace_dir)
        # 执行包归位 runs/{run_id}/packages/{task_id}——挂 run_id 与
        # agent_logs/results 同层可关联（旧布局 workspace/{task_id} 同名重跑
        # 互相覆盖且无法归属运行）。write_package 的目的地由
        # sut_tools.workspace_dir 决定，逐 run 注入包根。
        run_packages_root = workspace / "runs" / run_id / "packages"
        # 逐 run 注入包根（SUTToolServer 与语义工具注册表同根，产物落同一执行包）
        self._inject_workspace(run_packages_root)
        # 目录模式机械白名单：task.directory_path 由任务作者配置（非 LLM 运行时
        # 决定），注入为文件工具允许根——workspace 边界不挡目录模式扫描
        self.sut_tools.extra_allowed_roots = (
            [Path(task.directory_path)] if task.directory_path else []
        )
        self._clear_stale_tool_state()
        package_dir = run_packages_root / task.id
        log_dir = workspace / "runs" / run_id / "agent_logs"

        logger = SessionLogger(run_id, task.id, log_dir=log_dir)
        guard = BudgetGuard(self.config.max_budget_usd)
        logger.log_start(task.input, task.constraints)

        try:
            graph = self._ensure_graph()
            result = await graph.ainvoke(
                {"messages": [{"role": "user", "content": self._build_task_prompt(task)}]},
                # recursion_limit 假设「1 轮 ≈ 2 step（模型 + 工具节点）」——
                # 深层假设：给执行图加会推进 step 的中间件时须同步校准此倍数
                config={
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
        """构建 DeepAgents 图：模型桥接 + 工具显式绑定。

        不接 checkpointer：单任务单发 ainvoke 无恢复需求；且 langgraph 会经
        put/put_writes/get_tuple 高频触达 saver，文件全量读写实现会拖垮执行
        （实测 CPU 空转）。WorkspaceCheckpointer 保留为独立组件，待其实现
        语义正确的真 saver（增量写 + pending_writes 按 checkpoint_id 索引）
        后再接回。
        """
        try:
            from deepagents import create_deep_agent
        except ImportError:
            raise AgentError(
                "ExecutionAgent 需要 deepagents（DeepAgents 底座）。"
                "请执行: pip install 'agent-eval[agent]'",
                details={"missing_module": "deepagents"},
            ) from None
        tools = [tool for server in self.tool_servers for tool in server.to_langchain_tools()]
        return create_deep_agent(
            model=build_chat_model(self.config.llm_role, self.config.model),
            tools=tools,
            system_prompt=self._build_system_prompt(),
            # 工具面复位：create_deep_agent 对内置工具 additive 合并——不清则
            # StateBackend 虚拟 FS 的 ls/read_file 等混进模型可见面（真实路径
            # 返回 "No files found"，run 20260911_010507 最后两轮烧在其上），
            # 且内置 read_file 与自研白名单 read_file 同名歧义。共享实现见
            # agent/core/tool_filter.py（工作台域同款，中间件名按域区分）
            middleware=[build_toolset_filter(tools, middleware_name="ExecutionToolsetFilter")],
        )

    # ─── Prompt 构建（拼装见 executor/prompts.py，本类仅传参委托） ───

    def _build_system_prompt(self) -> str:
        """System Prompt（模板见 execution_agent_prompts.yaml，构建见 executor/prompts.py）。"""
        return build_system_prompt(
            tool_servers=self.tool_servers,
            max_turns=self.config.max_turns,
            max_retries=self.config.max_retries,
        )

    def _build_task_prompt(self, task: Task) -> str:
        """Task Prompt（模板见 execution_agent_prompts.yaml，构建见 executor/prompts.py）。"""
        return build_task_prompt(task, workspace_dir=Path(self.config.workspace_dir))

    _extract_instruction = staticmethod(extract_instruction)

    # ─── 工具注册表状态 ───

    def _clear_stale_tool_state(self) -> None:
        """跨任务清账：last_run 是语义工具注册表上的单槽缓存，而实例整个任务集共享
        ——本任务 SUT 调用全部失败时不产生新记录，兜底回填/物化会拿到上一任务
        的残留（2026-09-10 实测串台：physics 四次尝试全超时，answer.md 与评估
        对象是 chinese 留下的《春》完成通知，答非所问全 0 分）。
        """
        for server in self.tool_servers:
            if getattr(server, "last_run", None) is not None:
                server.last_run = None

    def _last_sut_run(self) -> dict[str, Any] | None:
        """取工具注册表记录的最近一次 SUT run 摘要（AgentProtocolToolServer.last_run）。"""
        for server in self.tool_servers:
            last: dict[str, Any] | None = getattr(server, "last_run", None)
            if last:
                return last
        return None

    # ─── ExecutionPackage 构建（物化编排见 executor/package_writer.py） ───

    async def _build_package(
        self,
        session: AgentSession,
        task: Task,
        package_dir: Path,
    ) -> ExecutionPackage:
        """从 Agent 会话构建 ExecutionPackage（补齐/守卫细节见 executor/package_writer.py）。"""
        return await finalize_execution_package(
            package_dir,
            task,
            session,
            sut_tools=self.sut_tools,
            llm_role=self.config.llm_role,
            last_sut_run=self._last_sut_run(),
        )

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
        await ensure_failure_package(package_dir, task.id, str(error), sut_tools=self.sut_tools)
        logger.log_end(cost_usd=guard.spent_usd, tokens_used=guard.total_tokens)
        logger.close()
