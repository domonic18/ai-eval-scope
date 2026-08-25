"""ExecutionAgent — 基于 DeepAgents（Python）的执行 Agent（arch/03 §三 v4.6）。

端到端驱动评测执行流程：理解任务、调用 SUT Tools、处理错误、收集结果、
生成 ExecutionPackage。底座为 deepagents 的 create_deep_agent（惰性导入，
[agent] optional extra）；模型经 build_chat_model 从角色注册表双协议桥接；
BudgetGuard/SessionLogCallback 以 LangGraph 回调注入（预算/结构化日志）。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from agent_eval.agent.callbacks import BudgetGuard, SessionLogCallback
from agent_eval.agent.hooks import SessionLogger
from agent_eval.agent.model_bridge import build_chat_model
from agent_eval.agent.session import AgentSession
from agent_eval.agent.sut_tools import SUTToolServer
from agent_eval.config.paths import PACKAGE_ROOT
from agent_eval.core.exceptions import (
    AgentError,
    AgentTimeoutError,
    BudgetExceededError,
)
from agent_eval.execution.models import AgentConfig, ProcessMetrics, Task, TaskSet
from agent_eval.storage.package import ExecutionPackage, generate_run_id

# 执行 Agent 提示词资产（prompt 在 YAML 中维护，不 hardcode；对齐 summary_prompt.yaml 惯例）
_PROMPTS_PATH = PACKAGE_ROOT / "assets" / "configs" / "execution_agent_prompts.yaml"


@lru_cache(maxsize=1)
def _load_prompts() -> dict[str, Any]:
    """加载 execution_agent_prompts.yaml → {system_prompt, task_prompt}。"""
    try:
        data = yaml.safe_load(_PROMPTS_PATH.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as e:
        raise AgentError(
            f"执行 Agent 提示词资产损坏: {_PROMPTS_PATH}（{e}）",
            details={"path": str(_PROMPTS_PATH)},
        ) from e
    if not isinstance(data, dict) or not data.get("system_prompt") or not data.get("task_prompt"):
        raise AgentError(
            f"执行 Agent 提示词资产结构不完整（需 system_prompt/task_prompt 两段）: {_PROMPTS_PATH}",
            details={"path": str(_PROMPTS_PATH)},
        )
    return data


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _is_recursion_error(error: BaseException) -> bool:
    """识别 LangGraph GraphRecursionError（按类名，避免硬依赖 langgraph）。"""
    return type(error).__name__ == "GraphRecursionError"


class ExecutionAgent:
    """基于 DeepAgents 的执行 Agent，端到端驱动评测执行流程。

    - 模型：LLM 角色注册表（arch/16 §6.2-四）→ build_chat_model() 构造 ChatModel（双协议，模型无关）
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
            extra_tool_servers: 追加工具注册表（如 AgentProtocolToolServer，
                arch/03 §4.0.6 语义工具面），与 SUT Tools 一同显式绑定。
        """
        self.config = config
        self.sut_tools = sut_tools or SUTToolServer(
            config.sut_tools_config, workspace_dir=config.workspace_dir
        )
        # 外部注入的注册表（如 AgentProtocolToolServer）同样以 config.workspace_dir
        # 为落盘根——write_package/collect_results 的目的地不交给 LLM 决定
        self.sut_tools.workspace_dir = Path(config.workspace_dir)
        self.tool_servers: list[Any] = [self.sut_tools, *(extra_tool_servers or [])]
        self._graph: Any = None

    # ─── 对外入口 ───

    async def run_task_set(
        self, task_set: TaskSet, *, run_id: str | None = None
    ) -> tuple[str, list[ExecutionPackage]]:
        """批量执行任务集（共享 run_id），返回 (run_id, 执行包列表)。

        run_id 可由调用方（CLI）注入——用于运行清单登记与外部关联。
        """
        run_id = run_id or generate_run_id()
        packages = [await self.run_task(task, run_id=run_id) for task in task_set.tasks]
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
        # W7（arch/16 §三）：执行包归位 runs/{run_id}/packages/{task_id}——
        # 挂 run_id 与 agent_logs/results 同层可关联（旧布局 workspace/{task_id}
        # 同名重跑互相覆盖且无法归属运行）。write_package 的目的地由
        # sut_tools.workspace_dir 决定，逐 run 注入包根。
        run_packages_root = workspace / "runs" / run_id / "packages"
        self.sut_tools.workspace_dir = run_packages_root
        package_dir = run_packages_root / task.id
        log_dir = workspace / "runs" / run_id / "agent_logs"

        logger = SessionLogger(run_id, task.id, log_dir=log_dir)
        guard = BudgetGuard(self.config.max_budget_usd)
        logger.log_start(task.input, task.constraints)

        try:
            graph = self._ensure_graph()
            result = await graph.ainvoke(
                {"messages": [{"role": "user", "content": self._build_task_prompt(task)}]},
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
        （v4.6.3 实测 CPU 空转）。WorkspaceCheckpointer 保留为独立组件，
        待 B4 实现语义正确的真 saver（增量写 + pending_writes 按
        checkpoint_id 索引）后再接回。
        """
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
            model=build_chat_model(self.config.llm_role, self.config.model),
            tools=tools,
            system_prompt=self._build_system_prompt(),
        )

    # ─── Prompt 构建（arch/03 §3.3/§3.4） ───

    def _describe_all_tools(self) -> str:
        """汇总全部工具注册表（SUT Tools + 追加注册表）的描述清单。"""
        return "\n".join(server.describe_tools() for server in self.tool_servers)

    def _build_system_prompt(self) -> str:
        """System Prompt：角色职责 + 可用工具 + 执行规则 + 输出规范（模板见 execution_agent_prompts.yaml）。"""
        template: str = _load_prompts()["system_prompt"]
        return template.format(
            tools=self._describe_all_tools(),
            max_turns=self.config.max_turns,
            max_retries=self.config.max_retries,
        )

    def _build_task_prompt(self, task: Task) -> str:
        """Task Prompt：任务输入/预期/约束 + 目录模式说明 + 写包指令（分段模板见 execution_agent_prompts.yaml）。"""
        segments: dict[str, str] = _load_prompts()["task_prompt"]
        package_dir = Path(self.config.workspace_dir) / task.id
        parts = [
            segments["header"].format(task_id=task.id),
            segments["input"].format(
                task_input=json.dumps(task.input, ensure_ascii=False, indent=2)
            ),
        ]
        if task.expected:
            parts.append(
                segments["expected"].format(
                    expected=json.dumps(task.expected, ensure_ascii=False, indent=2)
                )
            )
        if task.constraints:
            parts.append(
                segments["constraints"].format(
                    constraints=json.dumps(task.constraints, ensure_ascii=False, indent=2)
                )
            )
        if task.input_mode == "directory" and task.directory_path:
            parts.append(
                segments["directory_mode"].format(
                    directory_path=task.directory_path,
                    file_patterns=task.file_patterns,
                )
            )
        parts.append(segments["footer"].format(package_dir=package_dir))
        return "\n\n".join(p.rstrip("\n") for p in parts)

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
                task_id=task.id,
                success=False,
                error="Agent 未调用 write_package，已由 ExecutionAgent 兜底写包",
            )
        self._ensure_task_file(task, package_dir)
        self._ensure_trace_file(session, package_dir)
        self._ensure_answer_file(package_dir)
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
        response: dict[str, Any] = {
            "messages": len(session.messages),
            "tool_calls": session.tool_call_count,
        }
        # 回填 SUT 最终回答（trace 只存计数时下游 eval 拿不到评估对象，v4.6.4）
        sut_run = self._last_sut_run()
        if sut_run is not None:
            response["sut"] = sut_run
        trace = {
            "request": {"executor": "ExecutionAgent", "llm_role": self.config.llm_role},
            "response": response,
            "started_at": session.started_at,
            "finished_at": session.finished_at or _now_iso(),
            "error": None,
        }
        trace_file.write_text(json.dumps(trace, ensure_ascii=False, indent=2), encoding="utf-8")

    def _last_sut_run(self) -> dict[str, Any] | None:
        """取工具注册表记录的最近一次 SUT run 摘要（AgentProtocolToolServer.last_run）。"""
        for server in self.tool_servers:
            last: dict[str, Any] | None = getattr(server, "last_run", None)
            if last:
                return last
        return None

    def _ensure_answer_file(self, package_dir: Path) -> None:
        """SUT 回答物化为 output/answer.md（对话型任务无产物文件；评估器按文件收集文本）。"""
        text = (self._last_sut_run() or {}).get("text") or ""
        if not text.strip():
            return
        output_dir = package_dir / "output"
        if output_dir.exists() and any(output_dir.iterdir()):
            return  # SUT 已有产物文件，不重复物化
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "answer.md").write_text(text, encoding="utf-8")

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
