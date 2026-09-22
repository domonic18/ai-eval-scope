"""AgentProtocolToolServer 状态与闸门 mixin — 任务级状态 / 预算闸门 / 简报注入 / 终局刷新。

服务端侧（不经 Agent）：run 摘要记录、超时预算、交互预算闸门、决策台账、
决策简报注入（挂点 b）、收尾终局快照刷新。仅供 ``protocol_tools``
``.AgentProtocolToolServer`` 组合（实例状态由组合主体 ``__init__`` 建立），
不独立使用。
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

from agent_eval.agent.core.tools import truncate
from agent_eval.agent.executor.briefing import (
    SutStateTracker,
    build_briefing,
)
from agent_eval.agent.executor.ledger import ResourceLedger, uninjected_ledger_refusal
from agent_eval.agent.executor.protocol_shared import (
    _BRIEFING_TOOLS,
    TIMEOUT_EVIDENCE_MAX_CHARS,
    TIMEOUT_RETRY_LIMIT,
)
from agent_eval.agent.executor.terminal import (
    TerminalObservation,
    classify_thread_state,
    log_sut_observation,
)
from agent_eval.core.exceptions import AgentEvalError, AgentProtocolTimeoutError
from agent_eval.core.types import TerminalKind
from agent_eval.execution.channels.agent_protocol import AgentProtocolChannel
from agent_eval.execution.channels.interrupts import ask_question_tool_call_ids
from agent_eval.execution.channels.thread_commands import COMMANDS_POLL_INTERVAL_S


class ProtocolStateMixin:
    """任务级状态 + 机械闸门 + 简报注入（组合用 mixin）。"""

    # 组合主体成员声明（仅注解，零运行时）——供类型检查器解析 self.* 引用
    channel: AgentProtocolChannel
    default_metadata: dict[str, Any]
    workspace_dir: Path | None
    last_run: dict[str, Any] | None
    _timeout_errors: list[str]
    ledger: ResourceLedger | None
    _tracker: SutStateTracker

    def _record_last_run(self, result: dict[str, Any], input: Any = None) -> None:
        """记录最近一次 run 的状态/线程/回答文本（截断前原文，供 trace 落盘）。

        input 一并记录：ExecutionAgent 的机械回显守卫据此判定「SUT 返回=请求原文」。
        interrupted 时提取待应答反问（interrupt_id/tool_call_id/题目），供
        answer_sut_questions 应答；回到 success 即清除（过时应答无意义）。
        """
        run = result.get("run") or {}
        output = result.get("output") or {}
        pending: dict[str, Any] | None = None
        if result.get("status") == "interrupted" and result.get("questions"):
            ids = ask_question_tool_call_ids(result.get("messages"))
            pending = {
                "interrupt_id": result["questions"][0].get("interrupt_id") or "",
                "tool_call_id": ids[-1] if ids else "",
                "questions": [
                    {k: v for k, v in q.items() if k != "interrupt_id"} for q in result["questions"]
                ],
            }
        self.last_run = {
            "status": result.get("status"),
            "thread_id": run.get("thread_id"),
            "run_id": run.get("run_id"),
            # commands 形态在顶层 text；runs 形态经 output_paths 提取到 output.text
            "text": result.get("text") or output.get("text") or "",
            "input": input,
            "pending": pending,
            # 合同一（arch/16 §4.6）：结构化交付不再当场丢弃（run 20260916_074046
            # sem_002：resources_found 等 _extract_output 产物此前只进 LLM 视野）
            "output": output or None,
        }
        # 观测载荷同步入台账（sut_observation 事件，载荷截断全量在 trace）
        log_sut_observation(self.ledger, source="run", run=self.last_run)
        # run 完成即活动：观察时间线记一笔（idle 计时从此刻起算）——简报
        # sut_state 的素材与 last_run 同源，不需要决策体另行拼凑
        self._tracker.observe(
            (result.get("status") or run.get("status")) == "running",
            str(self.last_run["text"] or ""),
        )

    def reset_task_state(self) -> None:
        """任务起点清账（ExecutionAgent._clear_stale_tool_state 统一调用）。

        last_run 单槽与超时计数都是任务集共享实例上的任务级状态——跨任务
        残留轻则串台（v4.12），重则让下一任务被误判超时预算耗尽。
        ledger 例外：账本随任务生灭，由 ExecutionAgent 在任务起点注入新实例
        （换新即清零），此处不清。观察时间线同属任务级状态，此处换新。
        """
        self.last_run = None
        self._timeout_errors.clear()
        self._tracker = SutStateTracker()

    def _timeout_budget_blocked(self) -> dict[str, Any] | None:
        """超时预算耗尽 → 返回拒绝载荷（不再触网）；未耗尽返回 None。"""
        if len(self._timeout_errors) <= TIMEOUT_RETRY_LIMIT:
            return None
        return {
            "status": "failed",
            "error": {
                "type": "TimeoutBudgetExhausted",
                "message": (
                    f"SUT 调用超时已达重试上限 {TIMEOUT_RETRY_LIMIT} 次——超时后重试只会"
                    "重烧同量级时长。不要再发起任何 SUT 执行调用（agent_run/run_on_thread/"
                    "agent_run_stream），直接 write_package(success=false, error=超时证据) 收尾"
                ),
            },
            "timeout_evidence": [
                truncate(text, TIMEOUT_EVIDENCE_MAX_CHARS) for text in self._timeout_errors
            ],
        }

    def _budget(self, action: str) -> dict[str, Any] | None:
        """交互预算闸门（arch/16 §4.3）：拒绝载荷（含 guidance）或 None 放行。

        账本未注入即拒绝（fail-closed）：装配链遗漏注入时闸门收紧而非静默
        放行——「无账本」不能等于「无额度」。
        """
        if self.ledger is None:
            return uninjected_ledger_refusal(action)
        return self.ledger.authorize(action)

    def _ledger_record(
        self, action: str, outcome: str, started: float, summary: Any = None
    ) -> None:
        """闸门放行后的结果留证（授权计数在 authorize 已完成，此处只补证据流）。"""
        if self.ledger is not None:
            self.ledger.record(
                action, outcome, duration_s=time.monotonic() - started, summary=summary
            )

    def _log_decision(self, action: str, verdict: str | None, rationale: str | None) -> None:
        """仲裁决策落台账（arch/16 §5.2：结论为受控枚举 + rationale 供复盘）。"""
        ledger = self.ledger
        if ledger is None or ledger.evidence is None:
            return
        ledger.evidence.log(
            "decision",
            action=action,
            verdict=verdict,
            rationale=truncate(rationale, 500) if rationale else None,
        )

    def _rationale_refusal(self) -> dict[str, Any]:
        """催促缺 rationale 的资格拒绝（arch/16 §5.2 十二连催病理的机械对应物）。

        rationale 是资格不是额度——缺理由不消耗催促额度，也不触网；额度闸门
        管「还能催几次」，本闸门管「每次催促必须是决策而非习惯」。拒绝载荷
        附可抄模板（Phase 2.1：抽象要求改为示例填法，重放显示零依从的根因）；
        同 action 连拒升级语由账本统一追加（连拒 3 次起）。
        """
        error = {
            "budget": "nudge_rationale",
            "message": (
                "run_on_thread 缺少 rationale 参数。催促的 rationale 直接按此模板填："
                'rationale="简报显示空闲 180s、无产物候选、无待答反问，需向 SUT 确认进度"'
                "——引用 briefing.sut_state 的具体数值"
                "（idle_for_s / artifact_candidates / pending_questions），"
                "不要写「请继续」类空话。"
            ),
        }
        if self.ledger is not None:
            self.ledger.register_refusal("nudge", error)
        if self.ledger is not None and self.ledger.evidence is not None:
            self.ledger.evidence.log("gate_refusal", action="nudge", **error)
        return {"status": "failed", "error": {"type": "NudgeRationaleRequired", **error}}

    def _enrich_result(self, result: Any, *, tool: str) -> Any:
        """挂点 b（arch/16 §5.1）：动作工具结果统一前置决策简报。

        仅账本就位（ExecutionAgent 驱动）时注入——gate 拒绝载荷同享简报
        （拒的是动作，简报告诉决策体接下来该去哪）；直连使用（无账本）
        恒等返回，行为不变。
        """
        if self.ledger is None or tool not in _BRIEFING_TOOLS or not isinstance(result, dict):
            return result
        result.setdefault(
            "briefing",
            build_briefing(ledger=self.ledger, tracker=self._tracker, last_run=self.last_run),
        )
        return result

    def _register_timeout_or_reraise(self, error: AgentProtocolTimeoutError) -> dict[str, Any]:
        """登记一次 SUT 调用超时；预算未耗尽则原样抛出（tool_guard 转 failed 结果）。"""
        self._timeout_errors.append(str(error))
        blocked = self._timeout_budget_blocked()
        if blocked is not None:
            return blocked
        raise error

    def _merge_metadata(self, metadata: dict[str, Any] | None) -> dict[str, Any]:
        return {**self.default_metadata, **(metadata or {})}

    async def refresh_final_state(self, *, settle_timeout_s: float = 120.0) -> None:
        """收尾终局快照刷新（arch/16 §4.5 snapshot/reconcile，壳层机械动作非 LLM 工具）。

        run 工具返回时刻 ≠ SUT 最终发言时刻：阶段切换空窗误判终态后，后续取证
        （read_thread_state）只读不回写，last_run.text 冻结在中间播报，answer.md
        随之冻结（run 20260912_000410）。由 ExecutionAgent 在 freeze（包物化）前
        机械调用：等待线程终态（snapshot），把终局事实全量回写 last_run
        （reconcile：text 经 final_delivery 归一提取，output/questions 一并对账）。

        - 门控：无 last_run/thread_id 或非 commands 形态直接返回（runs 形态
          thread_state 直接 raise；generic_http 无线程概念，无本方法自然跳过）；
        - settle 判据归一（合同二，arch/16 §4.6）：classify_thread_state 分类，
          interrupt_pending 是一等终态单采样立即返回——interrupt 线程 ``next``
          永不清空，此前自建循环只看 ``next`` 会空转满 120s 带旧值早退（run
          20260916_074046 neg_001）；空转仅对 no_evidence 生效；
        - settle_timeout_s 内未得终态、线程 404 或通道错误：保留现值静默返回
          ——收尾取证失败不得 fail 任务、不得破坏失败包物化；
        - 直调通道不经 _budget("state_poll")：收尾取证不耗执行 Agent 的轮询额度
          （对齐「取证/下载/写包不设闸」惯例），留证走 ledger.record；
        - 只改 text/output/pending：input 保留原值（guard_echo_answer 以 input
          vs text 比对回显，动 input 守卫语义漂移）。
        """
        last = self.last_run
        thread_id = (last or {}).get("thread_id")
        if not last or not thread_id or self.channel.sut.protocol_flavor != "commands":
            return
        started = time.monotonic()
        deadline = started + settle_timeout_s
        terminal: TerminalObservation | None = None
        terminal_values: dict[str, Any] = {}
        try:
            while terminal is None:
                state = await self.channel.thread_state(thread_id)
                if state is None:
                    # 线程不存在：不会再有更新的终局事实，保留现值
                    self._ledger_record(
                        "state_poll", "ok", started, summary={"final_refresh": "thread_not_found"}
                    )
                    return
                values = state.get("values") or {}
                obs = classify_thread_state(
                    state,
                    interrupt_types=self.channel.sut.interrupt_types,
                    output=self.channel._extract_output(values),
                )
                if obs.kind is not TerminalKind.NO_EVIDENCE:
                    terminal = obs
                    terminal_values = values
                    break
                if time.monotonic() >= deadline:
                    self._ledger_record(
                        "state_poll", "ok", started, summary={"final_refresh": "settle_timeout"}
                    )
                    return
                await asyncio.sleep(COMMANDS_POLL_INTERVAL_S)
        except AgentEvalError as e:  # 网络抖动/通道错误：静默降级，不破坏收尾
            self._ledger_record(
                "state_poll", "error", started, summary={"final_refresh": str(e)[:200]}
            )
            return
        values = terminal_values
        self._tracker.observe(False, json.dumps(values, ensure_ascii=False, default=str))
        self._ledger_record(
            "state_poll",
            "ok",
            started,
            summary={"final_refresh": terminal.kind.value, "thread_busy": False},
        )
        # reconcile（合同二/三）：终局事实全量回写——text 经 final_delivery 归一
        # 提取（tool_call 交付 SUT 不再落在首句播报），结构化 output 与反问挂起
        # 一并对账；观测载荷入台账
        if terminal.text and terminal.text != last.get("text"):
            last["text"] = terminal.text
        last["delivery_via"] = terminal.via
        if terminal.output is not None and terminal.output != {}:
            last["output"] = terminal.output
        if terminal.questions:
            ids = ask_question_tool_call_ids(values.get("messages") or [])
            last["pending"] = {
                "interrupt_id": terminal.questions[0].get("interrupt_id") or "",
                "tool_call_id": ids[-1] if ids else "",
                "questions": [
                    {k: v for k, v in q.items() if k != "interrupt_id"} for q in terminal.questions
                ],
            }
        log_sut_observation(self.ledger, source="final_refresh", run=last)
