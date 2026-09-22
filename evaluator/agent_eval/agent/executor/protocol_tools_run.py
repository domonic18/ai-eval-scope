"""AgentProtocolToolServer 执行类工具 mixin — agent_run / agent_run_stream / create_thread / run_on_thread / read_thread_state。

Agent 可调用；通道异常经 tool_guard 转 failed 结果交 Agent 自修复。
仅供 ``protocol_tools.AgentProtocolToolServer`` 组合，不独立使用。
"""

from __future__ import annotations

import json
import time
from typing import Any

from agent_eval.agent.core.tools import truncate
from agent_eval.agent.executor.briefing import ARBITRATION_VERDICTS
from agent_eval.agent.executor.protocol_shared import (
    EVENT_DATA_MAX_CHARS,
    MAX_STREAM_EVENTS,
    bounded_result,
    briefing_enriched,
    tool_guard,
)
from agent_eval.agent.executor.protocol_state import ProtocolStateMixin
from agent_eval.core.exceptions import (
    AgentProtocolTimeoutError,
    ToolExecutionError,
)
from agent_eval.execution.channels.interrupts import pending_ask_questions


class ProtocolRunToolsMixin(ProtocolStateMixin):
    """执行与取证工具（dispatch / 多轮线程 / 只读仲裁）（组合用 mixin）。"""

    @briefing_enriched
    @tool_guard
    async def agent_run(
        self,
        input: dict[str, Any] | str,
        exec_mode: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """执行被测 Agent：按 exec_mode 走 wait/background/stream。"""
        blocked = self._timeout_budget_blocked()
        if blocked is not None:
            return blocked
        refused = self._budget("dispatch")
        if refused is not None:
            return refused
        started = time.monotonic()
        try:
            result = await self.channel.run(
                input, exec_mode=exec_mode, metadata=self._merge_metadata(metadata)
            )
        except AgentProtocolTimeoutError as e:
            self._ledger_record("dispatch", "timeout", started)
            return self._register_timeout_or_reraise(e)
        self._ledger_record("dispatch", "ok", started, summary=result.get("status"))
        self._record_last_run(result, input)
        return bounded_result(result)

    @briefing_enriched
    @tool_guard
    async def agent_run_stream(
        self,
        input: dict[str, Any] | str,
        stream_mode: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """流式执行并聚合（未知事件保留在 events，完整原文可写入 trace）。"""
        blocked = self._timeout_budget_blocked()
        if blocked is not None:
            return blocked
        refused = self._budget("dispatch")
        if refused is not None:
            return refused
        started = time.monotonic()
        try:
            result = await self.channel.run_stream(
                input, stream_mode=stream_mode, metadata=self._merge_metadata(metadata)
            )
        except AgentProtocolTimeoutError as e:
            self._ledger_record("dispatch", "timeout", started)
            return self._register_timeout_or_reraise(e)
        self._ledger_record("dispatch", "ok", started, summary=result.get("status"))
        self._record_last_run(result, input)
        result["events"] = [
            {
                "event": e.get("event"),
                "data": truncate(
                    json.dumps(e.get("data"), ensure_ascii=False, default=str), EVENT_DATA_MAX_CHARS
                ),
            }
            for e in result.get("events", [])[:MAX_STREAM_EVENTS]
        ]
        return bounded_result(result)

    @tool_guard
    async def create_thread(self, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        """创建多轮会话线程。"""
        return await self.channel.create_thread(self._merge_metadata(metadata))

    @briefing_enriched
    @tool_guard
    async def run_on_thread(
        self,
        thread_id: str,
        input: dict[str, Any] | str,
        metadata: dict[str, Any] | None = None,
        rationale: str | None = None,
    ) -> dict[str, Any]:
        """在既有线程上执行一轮（催促/续跑必须附 rationale——每次打扰都应是决策）。

        rationale 缺失即拒绝且不耗额度（NudgeRationaleRequired，资格闸门）；
        提供则落 decision 台账（verdict 缺省 stalled——催促的前提判断），
        供事后复盘每一次催促的依据。
        """
        if not (isinstance(rationale, str) and rationale.strip()):
            return self._rationale_refusal()
        blocked = self._timeout_budget_blocked()
        if blocked is not None:
            return blocked
        refused = self._budget("nudge")
        if refused is not None:
            return refused
        self._log_decision("nudge", "stalled", rationale)
        started = time.monotonic()
        try:
            result = await self.channel.run_on_thread(
                thread_id, input, metadata=self._merge_metadata(metadata)
            )
        except AgentProtocolTimeoutError as e:
            self._ledger_record("nudge", "timeout", started)
            return self._register_timeout_or_reraise(e)
        self._ledger_record("nudge", "ok", started, summary=result.get("status"))
        self._record_last_run(result, input)
        return bounded_result(result)

    @briefing_enriched
    @tool_guard
    async def read_thread_state(
        self,
        thread_id: str,
        verdict: str | None = None,
        rationale: str | None = None,
    ) -> dict[str, Any]:
        """只读取证线程当前状态（GET state，不向 SUT 会话注入任何消息）。

        run 超时/无产物时的第一动作——先取证再决定是否打扰 SUT：
        thread_busy=false = SUT 已空闲，产物线索看 values（messages 保尾摘要）；
        有路径/链接直接 download_sut_file，无证据才 run_on_thread 索取。

        verdict/rationale（完成仲裁捕获）：提供即落 decision
        台账——取证是决策点，结论（complete/progressing/stalled/unknown）
        与理由必须留痕供复盘；verdict 非法枚举直接拒绝（受控枚举是契约）。
        """
        if verdict is not None and verdict not in ARBITRATION_VERDICTS:
            raise ToolExecutionError(
                f"非法仲裁结论 verdict={verdict!r}（合法: {ARBITRATION_VERDICTS}）"
            )
        refused = self._budget("state_poll")
        if refused is not None:
            return refused
        if verdict is not None or rationale:
            self._log_decision("state_poll", verdict, rationale)
        started = time.monotonic()
        state = await self.channel.thread_state(thread_id)
        if state is None:
            self._ledger_record("state_poll", "ok", started, summary="thread not_found")
            return {
                "status": "not_found",
                "thread_id": thread_id,
                "note": "线程不存在（commands 形态首个 run.start 才隐式建线程）",
            }
        values = state.get("values") or {}
        busy = bool(state.get("next") or [])
        # 观察时间线记一笔（bounded_result 截断前的全量摘要——摘要稳定是
        # idle 判定的前提，截断后的字符串反而可能抖动）
        self._tracker.observe(busy, json.dumps(values, ensure_ascii=False, default=str))
        self._ledger_record("state_poll", "ok", started, summary={"thread_busy": busy})
        return bounded_result(
            {
                "status": "success",
                "thread_id": thread_id,
                "thread_busy": busy,
                "pending_questions": pending_ask_questions(state, self.channel.sut.interrupt_types),
                "values": values,
            }
        )
