"""WorkbenchAgent — 评测工作台会话 Agent（REPL 式，形态对标 Claude Code）。

通用会话机 + 按域装配的工具面（域 = 工具面 + 提示词段 + 门禁策略）：场景包工程
（含 SUT 接入调试）是首个装配域，新域不影响会话机。

用户在 CLI 中持续输入自然语言（``你> ...``），Agent 经沙盒工具面改包、宿主展示
diff 并确认、校验门禁通过后落盘；多轮会话共享消息历史与暂存区。对话要点持久化到
``workspace/agent_sessions/``，草稿续作（新进程）时自动注入此前对话，跨会话不失忆。

每轮 :meth:`turn` 流程::

    你> <自然语言需求>
      → 图调用（Agent 输出计划 → 调工具写暂存 → 自检 preview_diff）
        ↳ recursion_limit 撞线 → 自动开新段续跑（≤ max_segments，checkpoint 事件）
      → 宿主 confirm_fn(reply, diff)：False = 回滚本轮（暂存清空，对话保留）
      → validate_package 门禁：失败则把 errors 注入下一轮回改（≤ max_fix_rounds）
      → commit() 原子落盘 + 会话日志

失败语义：**唯一的失败是用户放弃**。撞线分段耗尽 / Ctrl+C 中断 / LLM 瞬时错误 /
预算到界一律 = 暂停保现场（salvage 捞检查点半途消息并入历史，暂存不动），用户可
「继续」接着干或显式「放弃」（:meth:`abandon_pending`，唯一回滚触发器）。

职责分层：数据类型 workbench_types / 会话记忆 workbench_memory / 提示词资产
workbench_prompts / 落盘对账门禁 workbench_gates / langgraph 消息面
workbench_messages；本模块是会话机编排（装配 + turn 主循环 + 暂停续作 + 落盘）。
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from agent_eval.agent.core.callbacks import BudgetGuard
from agent_eval.agent.workbench.gates import sut_evidence_gate
from agent_eval.agent.workbench.memory import (
    SessionStore,
    session_key,
)
from agent_eval.agent.workbench.memory import (
    resume_messages as _resume_messages,
)
from agent_eval.agent.workbench.messages import (
    is_recursion_limit as _is_recursion_limit,
)
from agent_eval.agent.workbench.messages import (
    last_ai_text as _last_ai_text,
)
from agent_eval.agent.workbench.messages import (
    repair_orphan_tool_calls,
    salvage_state,
    stream_collect,
)
from agent_eval.agent.workbench.prompts import (
    load_prompts as _load_prompts,
)
from agent_eval.agent.workbench.prompts import (
    render_first_turn,
    render_intro,
)
from agent_eval.agent.workbench.sut_probe import SUTProbeToolServer
from agent_eval.agent.workbench.tool_filter import build_toolset_filter
from agent_eval.agent.workbench.tools import PackageToolServer
from agent_eval.agent.workbench.types import TurnResult, WorkbenchAgentConfig
from agent_eval.config.paths import paths
from agent_eval.core.exceptions import AgentError, BudgetExceededError
from agent_eval.execution.auth.credentials import CredentialStore

__all__ = [
    "TurnResult",
    "WorkbenchAgent",
    "WorkbenchAgentConfig",
    "run_turn",
]

# 任务清单纪律（注入 TodoListMiddleware 的 system_prompt，替代其过长默认版）：
# 单一事实源在中间件（工具与纪律同源注入），域提示词资产不重复维护
_TODO_SYSTEM_PROMPT = (
    "面对多步复杂任务（约 ≥3 步或跨多文件），先用 write_todos 建任务清单再动手："
    "每项一句话、可独立验证；保持恰好一项 in_progress；每完成一项立即把整份清单"
    "重写更新状态；过程中发现的新子任务随时补录；简单任务（一两步）不必建清单。"
)


class WorkbenchAgent:
    """工作台会话 Agent（一个实例 = 一次 REPL 会话，跨轮共享历史与暂存）。

    ``domain`` 为域档位（缺省场景包域）：选择提示词段；工具面当前固定为
    包域文件沙盒 + SUT 探测，新域按档位扩展装配。
    """

    def __init__(
        self,
        pkg_root: Path,
        *,
        config: WorkbenchAgentConfig | None = None,
        domain: str = "scenario_package",
        llm_role: str = "agent",
        log_dir: Path | None = None,
        ask_fn: Any = None,  # async (question, *, options, secret) -> str | None
    ) -> None:
        self.config = config or WorkbenchAgentConfig()
        self.domain = domain  # 域档位：选择提示词段与门禁策略
        self.server = PackageToolServer(Path(pkg_root), ask_fn=ask_fn)
        # SUT 接入调试工具面：与文件沙盒并列；凭证域隔离到密钥区。
        # fact_sink：探测验证成功的事实由服务端机械回填进创建骨架（五阶段流程，
        # arch/15）——事实不经 LLM 转述，「验证过了又来一遍」从源头消失
        self.probe = SUTProbeToolServer(
            ask_fn=ask_fn,
            credential_store=CredentialStore(),
            budgets=self.config.probe_budgets,
            timeout_s=self.config.probe_timeout_s,
            log_path=None,  # 探测证据随 agent_logs 统一落盘，见 _log_path
            fact_sink=self.server.append_skeleton_fact,
        )
        # 机械物化通道：write_sut_config 从探测账本原样注入 auth（两 server 构造
        # 互需对方能力，probe 先带 fact_sink 装配，账本在此回绑包沙盒）
        self.server.ledger = self.probe
        self.llm_role = llm_role
        self._messages: list[Any] = []
        # 预算护栏会话级累计（跨段/跨轮不清零）；内存检查点仅作事故现场保存器
        # （成功路径宿主持有消息重放，架构不变）
        self._budget_guard = BudgetGuard(self.config.budget_usd) if self.config.budget_usd else None
        self._checkpointer: Any = None  # 惰性创建（langgraph 属 [agent] extra）
        self._call_seq = 0
        self._last_thread_id = ""
        # 会话记忆持久化（跨进程续作）：同一包目录命中同一记录文件
        self._session_store = SessionStore(
            paths.default_workspace / "agent_sessions" / session_key(Path(pkg_root)),
            max_entries=self.config.max_dialogue_entries,
        )
        self._graph: Any | None = None
        self._log_path = (
            log_dir
            or paths.default_workspace
            / "agent_logs"
            / f"workbench_agent_{time.strftime('%Y%m%d_%H%M%S')}.jsonl"
        )
        self.probe.log_path = self._log_path  # 探测证据与会话日志同文件（时间线完整）

    # ─── 会话记忆（跨进程续作） ────────────────────────────────────

    @property
    def _dialogue(self) -> list[dict[str, str]]:
        """持久化对话要点（SessionStore 承载）。"""
        return self._session_store.dialogue

    @property
    def resumed_dialogue_count(self) -> int:
        """已续接的此前会话对话条数（0 = 全新会话），宿主据此显示续作提示。"""
        return len(self._session_store.dialogue)

    def _record_turn(self, user_text: str, reply: str) -> None:
        """记录本轮对话要点并持久化（仅 user/assistant 文本，不含工具流量）。"""
        self._session_store.record(user_text, reply, str(self.server.root))

    def relocate_root(self, final_root: Path) -> None:
        """包归位后重绑沙盒根：server 重定向 + 提示词重建 + 会话记录迁移。

        首次确认落盘即归位（v4.9）后由宿主调用——同一会话的后续轮次直接自然语言
        修改已归位的包。图在下一次 ``_invoke`` 时重建（系统提示的 ``{pkg_root}`` 在
        建图时烘焙；对话消息由宿主持有，重建不丢上下文）。会话记录文件迁移到新
        session_key——归位后跨进程续作（``--output`` 指回）命中同一记录，上下文不
        因归位断裂。文件迁移失败仅丢跨进程续作（key 仍切换，后续记录落新位），
        会话内不受影响。
        """
        final = Path(final_root).resolve()
        previous = self.server.root
        if final == previous:
            return
        old_file = self._session_store.session_file
        self.server.rebind_root(final)
        self._graph = None  # 系统提示烘焙了 {pkg_root}——下次调用重建
        new_file = old_file.parent / session_key(final)
        try:
            if old_file.exists():
                old_file.replace(new_file)
            skeleton = old_file.with_suffix(".SKELETON.md")
            if skeleton.exists():
                skeleton.replace(new_file.with_suffix(".SKELETON.md"))
        except OSError:
            pass  # 迁移失败仅影响跨进程续作；key 仍切换，后续记录落新位
        self._session_store.session_file = new_file
        self._log("relocate_root", previous=str(previous), final=str(final))
        # 归位事实进对话（沙盒根变了，Agent 须知道以新位置为准）——同放弃回滚的
        # 系统注记形态，防 Agent 仍引用旧草稿路径
        self._messages.append(
            (
                "user",
                f"（包已归位：沙盒根从 {previous} 迁移到 {final}，包内容不变。"
                "此后的文件读写、校验、落盘以新位置为准）",
            )
        )

    # ─── 组装 ─────────────────────────────────────────────────────

    def _describe_tools(self) -> str:
        specs = [*PackageToolServer.TOOL_SPECS, *SUTProbeToolServer.TOOL_SPECS]
        return "\n".join(f"- {s.name}: {s.description}" for s in specs)

    def _build_system_prompt(self) -> str:
        """分段装配：会话机段（base）+ 当前域档位的域段。"""
        prompts = _load_prompts()
        segments: dict[str, str] = prompts["domain_segments"]
        segment = segments.get(self.domain)
        if segment is None:
            raise AgentError(
                f"未装配的域档位: {self.domain}（可用: {', '.join(sorted(segments))}）",
                details={"domain": self.domain},
            )
        # 字面 replace 而非 str.format：提示词是散文体，含 { type: ... } 等
        # 字面大括号示例，format 会误当占位符吞掉
        template = f"{prompts['system_prompt_base']}\n{segment}"
        label = prompts.get("domain_labels", {}).get(self.domain, self.domain)
        return (
            template.replace("{domain}", label)
            .replace("{tools}", self._describe_tools())
            .replace("{pkg_root}", str(self.server.root))
            .replace("{assets_root}", str(self.server.assets_root))
        )

    def _build_graph(self) -> Any:
        """组装 DeepAgents 图（deepagents / langchain 为 [agent] extra，惰性导入）。"""
        try:
            from deepagents import create_deep_agent
        except ImportError:
            raise AgentError(
                "WorkbenchAgent 需要 deepagents（DeepAgents 底座）。请执行: uv sync --extra agent",
                details={"missing_module": "deepagents"},
            ) from None
        from langchain.agents.middleware import TodoListMiddleware
        from langgraph.checkpoint.memory import MemorySaver

        from agent_eval.agent.core.model_bridge import build_chat_model

        # 内存检查点无 IO、实例销毁即释放（不用文件版检查器：全量读写空转）
        self._checkpointer = MemorySaver()
        # 任务清单中间件（Claude Code TodoWrite 同款语义）：复杂任务先拆解再逐步
        # 执行；todos 走 langgraph state + 检查点，跨段续跑 / 会话续作自然保留。
        # deepagents 默认栈不含它（其默认 system_prompt 过长，见 deepagents
        # graph.py 注释）——此处传精简版；其注入的 write_todos 必须并入工具面
        # 白名单，否则被下方 ToolsetFilter 复位过滤掉（按实例 id 过滤）
        todo_mw = TodoListMiddleware(system_prompt=_TODO_SYSTEM_PROMPT)
        tools = [
            *self.server.to_langchain_tools(),
            *self.probe.to_langchain_tools(),
            *todo_mw.tools,
        ]
        return create_deep_agent(
            model=build_chat_model(self.llm_role),
            tools=tools,
            system_prompt=self._build_system_prompt(),
            checkpointer=self._checkpointer,
            # 复位模型可见工具面 = 宿主装配清单：deepagents 内置 ls/glob 跑
            # StateBackend 虚拟 FS（与磁盘无关），曾致「没有场景包」误判
            # （arch/15 v4.4；为何不用全局 harness profile 见 tool_filter 模块注释）
            middleware=[build_toolset_filter(tools), todo_mw],
        )

    # ─── 会话（宿主循环调用） ──────────────────────────────────────

    async def turn(
        self,
        user_text: str,
        *,
        confirm_fn: Callable[[str, str], bool],
        on_event: Callable[[dict[str, Any]], None] | None = None,
    ) -> TurnResult:
        """执行一轮：Agent 生成（流式）→ 用户确认 → 校验门禁（≤N 回改）→ 落盘/回滚。

        confirm_fn(reply, diff) 由 CLI 注入（全部应用 / 放弃）；放弃时本轮暂存清空，
        但消息历史保留（评测地址等讨论结论不丢失），以显式回滚说明收尾防 Agent
        误以为文件已写入。
        on_event 收流式进度事件（``token`` / ``tool_start`` / ``tool_end`` / ``phase``），
        CLI 据此直播工作过程；None = 静默。
        撞线/中断/瞬时错误/预算到界 = 暂停保现场：salvage 捞检查点半途消息并入
        历史、暂存不动——分段未耗尽时自动续跑，否则上抛或以
        aborted_reason=segment_limit/budget_exceeded 交还宿主（进度完整）。
        """
        self._log("turn_start", instruction=user_text)
        self.probe.new_turn()  # 重置 SUT 探测轮内预算（轮内总量约束）
        if not self._messages and self._dialogue:  # 跨进程续作：注入此前对话要点
            self._messages.extend(_resume_messages(self._dialogue, self.config))
        self._messages.append(("user", user_text))
        segment = 1
        while True:  # 自动分段续跑：同一对话/预算池/暂存，撞线开新段
            try:
                state = await self._invoke(self._messages, on_event=on_event)
                break
            except BaseException as exc:  # noqa: BLE001 — 统一暂停语义
                salvaged = await self._salvage_halfway()
                if salvaged:
                    self._messages = salvaged  # 检查点含输入——全线程替换保真
                if _is_recursion_limit(exc) and segment < self.config.max_segments:
                    segment += 1
                    self._log("segment_continue", segment=segment)
                    if on_event:
                        on_event(
                            {
                                "type": "phase",
                                "name": "checkpoint",
                                "segment": segment,
                                "max_segments": self.config.max_segments,
                            }
                        )
                    continue
                reply = _last_ai_text(self._messages)
                if isinstance(exc, asyncio.CancelledError):
                    reason = "interrupted"
                elif _is_recursion_limit(exc):
                    reason = "segment_limit"
                elif isinstance(exc, BudgetExceededError):
                    reason = "budget_exceeded"
                else:
                    reason = "error"  # 瞬时错误（LLM 断流等）：现场保留，可直接重试
                self._record_turn(user_text, reply)
                self._log("turn_paused", reason=reason, segment=segment, error=str(exc) or None)
                if reason in ("interrupted", "error"):
                    raise  # 宿主呈现失败/中断——现场保留，「继续」即接着跑
                return self._paused_result(reply, reason)

        self._messages = list(state.get("messages", self._messages))
        reply = _last_ai_text(self._messages)
        self._record_turn(user_text, reply)

        if not self.server.has_staged_changes:
            self._log("turn_end", committed=False, reason="no_changes")
            return TurnResult(reply=reply, diff="", staged=False)

        diff = self.server.render_diff()
        if on_event:
            on_event({"type": "phase", "name": "confirm"})
        if not confirm_fn(reply, diff):
            self.server.reset_staging()
            # 文件变更回滚，对话上下文保留——评测地址等讨论信息不因放弃而丢失
            self._messages.append(
                (
                    "user",
                    "（用户放弃了本轮文件变更：暂存已全部回滚，磁盘未做任何修改。"
                    "本轮对话中的结论与信息仍有效，可在后续轮次继续使用；"
                    "若需写入此前讨论的内容请重新执行）",
                )
            )
            self._log("turn_end", committed=False, reason="user_aborted")
            return TurnResult(reply=reply, diff=diff, staged=True, aborted_reason="user_aborted")

        result = await self._gate_and_commit(on_event)
        return TurnResult(
            reply=reply,
            diff=diff,
            staged=True,
            committed=result["committed"],
            committed_files=result.get("files", []),
            validation_errors=result.get("errors", []),
            aborted_reason=result.get("reason", ""),
        )

    # ─── 暂停与续作（唯一的失败是用户放弃） ────────────────────────

    async def _salvage_halfway(self) -> list[Any] | None:
        """撞线/中断后从检查点捞半途消息（孤儿 tool_call 已修复）；无现场返回 None。"""
        if self._graph is None or not self._last_thread_id:
            return None
        messages = await salvage_state(self._graph, self._last_thread_id)
        if not messages:
            return None
        return repair_orphan_tool_calls(messages)

    def _paused_result(self, reply: str, reason: str) -> TurnResult:
        """暂停轮结果：暂存与对话原样保留，宿主呈现「继续 / 放弃」处置。"""
        staged = self.server.has_staged_changes
        return TurnResult(
            reply=reply,
            diff=self.server.render_diff() if staged else "",
            staged=staged,
            aborted_reason=reason,
        )

    def abandon_pending(self) -> None:
        """用户显式放弃暂停轮的暂存改动（唯一的回滚触发器入口）。"""
        self.server.reset_staging()
        self._messages.append(
            (
                "user",
                "（用户放弃了此前中断轮的文件变更：暂存已全部回滚，磁盘未做任何修改。"
                "本轮对话中的结论与信息仍有效；若需写入此前讨论的内容请重新执行）",
            )
        )
        self._log("turn_end", committed=False, reason="user_aborted_after_pause")

    async def _gate_and_commit(
        self, on_event: Callable[[dict[str, Any]], None] | None = None
    ) -> dict[str, Any]:
        """校验门禁：失败注入错误回改（≤ max_fix_rounds），通过则原子落盘。"""
        templates: dict[str, str] = _load_prompts()["templates"]
        for round_no in range(1, self.config.max_fix_rounds + 1):
            validation = await self.server.validate_package()
            errors = [*validation["errors"], *sut_evidence_gate(self.server, self.probe)]
            if not errors:
                files = self.server.commit()
                self._archive_skeleton()
                self._log("commit", files=files)
                return {"committed": True, "files": files}
            self._log("validate_failed", round=round_no, errors=errors)
            if round_no == self.config.max_fix_rounds:
                return {"committed": False, "errors": errors, "reason": "max_fix_rounds"}
            self._messages.append(
                (
                    "user",
                    templates["fix_validation"].replace(
                        "{errors}", "\n".join(f"- {e}" for e in errors)
                    ),
                )
            )
            state = await self._invoke(self._messages, on_event=on_event)
            self._messages = list(state.get("messages", self._messages))
        return {"committed": False, "errors": ["校验轮次耗尽"], "reason": "max_fix_rounds"}

    def _archive_skeleton(self) -> None:
        """创建骨架归档为审计产物（过程事实与证据链不入包，但留档可查）。

        落会话记录同目录（按包根摘要命名，不与其它包撞）：包目录是源资产、会话
        结束要归位 cwd，过程产物跟进会污染包；写失败不影响提交（同 _log 容错）。
        """
        text = self.server.skeleton_archive
        if not text:
            return
        try:
            dest = self._session_store.session_file.with_suffix(".SKELETON.md")
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(text, encoding="utf-8")
        except OSError:
            pass  # 归档失败不影响提交

    async def _invoke(
        self,
        messages: list[Any],
        *,
        on_event: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        """单次图调用（测试注入点：monkeypatch 本方法可脱离 deepagents 回放状态机）。

        on_event 给定时改走流式（langgraph astream 三模，委托
        workbench_messages.stream_collect）；静默路径仍为一次性 ainvoke。
        """
        if self._graph is None:
            self._graph = self._build_graph()
        # langgraph 运行时配置：recursion_limit 是单段安全阀（非任务预算）；
        # 每次调用独立 thread_id——检查点仅作本调用的事故现场保存器
        self._call_seq += 1
        self._last_thread_id = f"wb-{self._call_seq}"
        runtime_config: dict[str, Any] = {
            "recursion_limit": self.config.max_turns * 2,
            "configurable": {"thread_id": self._last_thread_id},
        }
        if self._budget_guard is not None:
            runtime_config["callbacks"] = [self._budget_guard]
        if on_event is None:
            result: dict[str, Any] = await self._graph.ainvoke(
                {"messages": messages}, config=runtime_config
            )
            return result
        return await stream_collect(self._graph, messages, runtime_config, on_event)

    # ─── 自我介绍横幅（文案资产化，CLI 只渲染不写死） ────────────────

    def intro_text(self) -> str:
        """渲染启动横幅文案（{root}/{domains} 字面 replace；资产无 intro 段返回空）。"""
        return render_intro(_load_prompts(), self.domain, str(self.server.root))

    # ─── 首轮模板 ─────────────────────────────────────────────────

    @staticmethod
    def first_turn_text(
        instruction: str, *, new_package: bool = False, ref: str | None = None
    ) -> str:
        """组装首轮用户消息（新建包用 generate_new_package 模板）。

        ref 给定时钉住目标引用（Agent 不得自拟）；缺省时指引 Agent 按需求拟定
        并在计划首行明确给出（用户可自然语言改）。
        """
        return render_first_turn(instruction, new_package=new_package, ref=ref)

    # ─── 会话日志 ─────────────────────────────────────────────────

    def _log(self, event: str, **payload: Any) -> None:
        try:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            record = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "event": event, **payload}
            with self._log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        except OSError:
            pass  # 日志失败不影响会话

    @property
    def log_path(self) -> Path:
        return self._log_path


def run_turn(
    agent: WorkbenchAgent,
    user_text: str,
    *,
    confirm_fn: Callable[[str, str], bool],
    on_event: Callable[[dict[str, Any]], None] | None = None,
) -> TurnResult:
    """同步包装（CLI / REPL 调用）。"""
    return asyncio.run(agent.turn(user_text, confirm_fn=confirm_fn, on_event=on_event))
