"""Agent Protocol 语义工具面。

取代手搓 HTTP 请求：agent_run / agent_run_stream / create_thread /
run_on_thread / read_thread_state / answer_sut_questions / cancel_run /
get_agent_info / download_sut_file 九个语义工具，封装
AgentProtocolChannel 暴露给 DeepAgents 显式绑定（ToolExporterMixin）。
"""

from __future__ import annotations

import functools
import json
import re
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from agent_eval.agent.core.tools import ToolExporterMixin, ToolSpec, truncate
from agent_eval.agent.executor.briefing import (
    ARBITRATION_VERDICTS,
    SutStateTracker,
    build_briefing,
)
from agent_eval.agent.executor.ledger import ResourceLedger
from agent_eval.core.exceptions import (
    AgentEvalError,
    AgentProtocolError,
    AgentProtocolTimeoutError,
    ToolExecutionError,
)
from agent_eval.execution.channels.agent_protocol import AgentProtocolChannel
from agent_eval.execution.channels.interrupts import (
    ask_question_tool_call_ids,
    pending_ask_questions,
)
from agent_eval.execution.channels.message_digest import compact_messages

# 工具结果中大体量字段的截断上限（上下文经济性，非业务阈值）
VALUES_MAX_CHARS = 4000
EVENT_DATA_MAX_CHARS = 500
MAX_STREAM_EVENTS = 100
# 产物单文件下载上限（流式累计，超限即中止——防 SUT 指向超大文件耗尽磁盘/预算）
DOWNLOAD_MAX_BYTES = 50 * 1024 * 1024
# 【临时停用 2026-09-11，用户指示】staging 网关对 SUT 报告的产物路径（file:///workspace/...）
# 统一回 SPA 前端壳，下载必然失败且空烧执行步数（run 20260911_073626：3 连败促成
# 收尾拖延）——评测执行期间暂停下载功能，工具入口直接返回带收尾指引的 failed 结果
# （不触网、不耗下载预算）。恢复下载：置 True 即可，原逻辑无改动。
SUT_FILE_DOWNLOAD_ENABLED = False
# SPA 前端壳嗅探窗口（网关 fallback 页面远小于此）
SPA_SNIFF_BYTES = 4096
# 同任务 SUT 调用超时重试上限（机械守卫，不依赖 LLM 自觉——v4.8 哲学）：
# 真超时后再重试只会重烧同量级时长（run 20260910_134410 实测 chinese/english
# 各烧 3.7h/3.9h）。超过上限后 SUT 执行调用直接返回 TimeoutBudgetExhausted，
# 证据随结果透出供写失败包；只读取证与产物下载不受限
TIMEOUT_RETRY_LIMIT = 1
TIMEOUT_EVIDENCE_MAX_CHARS = 300


def _looks_like_spa_shell(path: Path) -> bool:
    """命中 SUT 网关 SPA 前端指纹：root 挂载点 + /assets/index-*.js 模块脚本。

    AG-UI 网关族对未知文件路径回前端壳而非 404（commands_agent_info 已记录的
    fallback 行为）——该「文件」不是产物，落包会让评估对象变成 JS 应用骨架
    （2026-09-11 实测：29.2k 课件被 396 字节 SPA 壳顶替入包）。双指纹同时命中
    才判定，含 root div 的正常 HTML 产物不受影响。
    """
    try:
        head = path.read_bytes()[:SPA_SNIFF_BYTES].decode("utf-8", errors="ignore")
    except OSError:
        return False
    return '<div id="root"' in head and "/assets/index-" in head


def tool_guard(
    fn: Callable[..., Awaitable[dict[str, Any]]],
) -> Callable[..., Awaitable[dict[str, Any]]]:
    """通道异常 → failed 结果（执行 Agent 可据以重试/降级/写错误包，而非中断图）。"""

    @functools.wraps(fn)
    async def wrapper(*args: Any, **kwargs: Any) -> dict[str, Any]:
        try:
            return await fn(*args, **kwargs)
        except AgentEvalError as e:
            return {
                "status": "failed",
                "error": {
                    "type": type(e).__name__,
                    "message": truncate(str(e), VALUES_MAX_CHARS),
                },
            }

    return wrapper


def briefing_enriched(
    fn: Callable[..., Awaitable[dict[str, Any]]],
) -> Callable[..., Awaitable[dict[str, Any]]]:
    """动作工具出口统一过 ``_enrich_result``（arch/16 §5.1 挂点 b）。

    叠在 tool_guard 之上（guard 先把通道异常转 failed，简报随后照常注入
    ——拒绝载荷同样需要指路）；方法层而非导出层（_json_tool）：直调与
    LangChain 导出两条路径行为一致。
    """

    @functools.wraps(fn)
    async def wrapper(self: Any, *args: Any, **kwargs: Any) -> dict[str, Any]:
        result = await fn(self, *args, **kwargs)
        return self._enrich_result(result, tool=fn.__name__)

    return wrapper


# 决策简报注入面（arch/16 §5.1 挂点 b）：对外部世界的昂贵动作 + 取证动作——
# 每次执行后刷新，决策体在下一轮看的是最新现实；取证收尾类工具
# （answer_sut_questions/cancel_run/get_agent_info/create_thread）不注入
_BRIEFING_TOOLS = frozenset(
    {
        "agent_run",
        "agent_run_stream",
        "run_on_thread",
        "read_thread_state",
        "download_sut_file",
    }
)

TOOL_SPECS: list[ToolSpec] = [
    ToolSpec(
        name="agent_run",
        description="执行被测 Agent（Agent Protocol）：wait 阻塞 / background 后台 / stream 流式，返回终态与产出物",
        method="agent_run",
    ),
    ToolSpec(
        name="agent_run_stream",
        description="流式执行被测 Agent 并聚合为完整输出 + 过程事件列表（需过程数据时使用）",
        method="agent_run_stream",
    ),
    ToolSpec(
        name="create_thread",
        description="创建多轮会话线程（对话式任务用；每 thread 同时仅一个活跃 run）",
        method="create_thread",
    ),
    ToolSpec(
        name="run_on_thread",
        description="在既有线程上执行一轮（多轮对话任务的后续轮次）",
        method="run_on_thread",
    ),
    ToolSpec(
        name="read_thread_state",
        description=(
            "只读查看线程当前状态（不注入新消息、不打断 SUT）：run 超时或拿不到"
            "产物时先取证——thread_busy=false 且 values/messages 有内容说明 SUT 已完成"
        ),
        method="read_thread_state",
    ),
    ToolSpec(
        name="answer_sut_questions",
        description=(
            "应答被测 Agent 的反问（run 返回 interrupted 且带 questions 时）："
            "按题目顺序逐题作答并续跑至终态；答案为选项值字符串或"
            " {'selected': [...], 'customText': '...'}"
        ),
        method="answer_sut_questions",
    ),
    ToolSpec(
        name="cancel_run",
        description="主动取消 run（interrupt 打断 / rollback 回滚，rollback 仅系统声明支持时用）",
        method="cancel_run",
    ),
    ToolSpec(
        name="get_agent_info",
        description="能力与 schema 发现（agents/search + schemas，接入自检用）",
        method="get_agent_info",
    ),
    ToolSpec(
        name="download_sut_file",
        description=(
            "下载被测系统生成的产物文件到执行包 output/（相对路径按 SUT 域解析；"
            "绝对 URL 仅允许 SUT 域与配置的 artifact_hosts）"
        ),
        method="download_sut_file",
    ),
]


class AgentProtocolToolServer(ToolExporterMixin):
    """Agent Protocol 语义工具注册表，绑定一个 AgentProtocolChannel。"""

    TOOL_SPECS = TOOL_SPECS
    discipline_key = "agent_protocol"  # 通道专属纪律段（execution_agent_prompts.yaml）

    def __init__(
        self,
        channel: AgentProtocolChannel,
        *,
        default_metadata: dict[str, Any] | None = None,
        workspace_dir: str | Path | None = None,
    ) -> None:
        """初始化工具注册表。

        Args:
            channel: Agent Protocol 通道实例。
            default_metadata: 附加到每次 run 的元数据（如 eval_run_id/sut_name，
                便于被测系统侧审计与限流豁免协商）。
            workspace_dir: 产物下载落盘根（download_sut_file 写
                {workspace_dir}/{task_id}/output/）；缺省 None，由 ExecutionAgent
                逐 run 注入包根——目的地是执行器基础设施，不由 LLM 决定。
        """
        self.channel = channel
        self.default_metadata = default_metadata or {}
        self.workspace_dir: Path | None = Path(workspace_dir) if workspace_dir else None
        # 最近一次 SUT run 摘要（ExecutionPackage trace 回填 SUT 回答文本用）
        self.last_run: dict[str, Any] | None = None
        # 本任务 SUT 调用超时留证（reset_task_state 逐任务清账）
        self._timeout_errors: list[str] = []
        # 交互预算账本（arch/16 §4.3）——缺省 None=闸门全放行（直连使用本注册表
        # 的旧路径不受影响）；ExecutionAgent 逐任务注入新实例（账本随任务生灭，
        # reset_task_state 不清它——换新即清零）
        self.ledger: ResourceLedger | None = None
        # SUT 状态观察时间线（arch/16 §5.1 决策简报素材）——reset_task_state
        # 逐任务换新，与账本同节奏
        self._tracker = SutStateTracker()

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
        }
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
        """交互预算闸门（arch/16 §4.3）：拒绝载荷（含 guidance）或 None 放行。"""
        if self.ledger is None:
            return None
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
        管「还能催几次」，本闸门管「每次催促必须是决策而非习惯」。
        """
        error = {
            "budget": "nudge_rationale",
            "message": (
                "run_on_thread 缺少 rationale 参数——催促必须引用简报证据"
                "（sut_state：空闲时长/产物候选/待答反问）说明为何此刻打扰 SUT。"
                "先 read_thread_state 取证补充依据，再决定是否催促。"
            ),
        }
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
        供事后复盘每一次催促的依据（arch/16 §5.2 验收门①）。
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

        verdict/rationale（完成仲裁捕获，arch/16 §5.2）：提供即落 decision
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

    @tool_guard
    async def answer_sut_questions(self, answers: list[Any]) -> dict[str, Any]:
        """应答被测 Agent 的 askQuestion 反问并续跑至终态（一次调用闭环）。

        answers 逐题对应最近一次 interrupted run 的 questions 顺序：字符串视为
        单选值，{"selected": [...], "customText": ...} 原样透传。应答经
        input.respond 提交后继续轮询到终态——评估 Agent 无需再手动 run_on_thread。

        恢复载荷为前端同款 ``{"answers": [逐题答案]}``（run 20260910_234613 实测：
        旧实现按 ask_question 工具调用 id 键控，SUT 端校验不到 answers 数组报
        「答案数据无效(非数组)未采纳」，SUT agent 视角=提问卡片失败 ×3 后放弃反问）。
        """
        pending = (self.last_run or {}).get("pending")
        if not pending:
            raise ToolExecutionError(
                "没有待应答的反问——仅当 agent_run/run_on_thread 返回 interrupted"
                "（带 questions）后才可调用本工具"
            )
        questions = pending.get("questions") or []
        if not isinstance(answers, list) or len(answers) != len(questions):
            received = len(answers) if isinstance(answers, list) else type(answers).__name__
            raise ToolExecutionError(
                f"反问共 {len(questions)} 题，收到 {received} 份答案，须逐题一一对应: "
                + json.dumps(questions, ensure_ascii=False)
            )
        response = {"answers": [_normalize_answer(a) for a in answers]}
        result = await self.channel.answer_interrupt(
            self.last_run.get("thread_id") or "", pending["interrupt_id"], response
        )
        self._record_last_run(result, answers)
        return bounded_result(result)

    @tool_guard
    async def cancel_run(self, run_id: str, action: str = "interrupt") -> dict[str, Any]:
        """主动取消 run。"""
        return await self.channel.cancel_run(run_id, action)

    @tool_guard
    async def get_agent_info(self, agent_id: str | None = None) -> dict[str, Any]:
        """能力与 schema 发现。"""
        return await self.channel.get_agent_info(agent_id)

    @briefing_enriched
    @tool_guard
    async def download_sut_file(
        self,
        url: str,
        task_id: str,
        filename: str | None = None,
    ) -> dict[str, Any]:
        """下载 SUT 产物文件到执行包 output/（随既有链路自动入包指纹与上报）。

        机械边界（不依赖 LLM 自觉）：相对路径按 base_url 解析；绝对 URL 的 host
        必须在白名单（base_url 域 ∪ sut.artifact_hosts）内，防 SUT 返回恶意地址；
        流式累计字节超 DOWNLOAD_MAX_BYTES 即中止。文件名经 basename 拍平防路径逃逸。

        【临时停用】SUT_FILE_DOWNLOAD_ENABLED=False 期间入口直接返回带收尾指引的
        failed 结果——不触网、不耗下载预算（停用缘由见常量注释）。
        """
        if not SUT_FILE_DOWNLOAD_ENABLED:
            self._ledger_record("download", "disabled", time.monotonic(), summary=url)
            return {
                "status": "failed",
                "error": {
                    "type": "ToolDisabled",
                    "message": (
                        "download_sut_file 临时停用（SUT 网关产物路径暂不可达，下载必然失败）。"
                        "不要重试下载；把产物路径与 SUT 回复原文作为证据，直接 "
                        "write_package 收尾（成功与否据已收集到的证据如实判定）"
                    ),
                },
                "url": url,
            }
        refused = self._budget("download")
        if refused is not None:
            return refused
        started = time.monotonic()
        dest_url, dest_path = self._download_destination(url, task_id, filename)
        try:
            try:
                size, content_type = await self._stream_download(dest_url, dest_path)
            except httpx.HTTPError as e:
                raise ToolExecutionError(f"产物下载传输失败: {e}", details={"url": dest_url}) from e
            if _looks_like_spa_shell(dest_path):
                raise ToolExecutionError(
                    "下载内容命中 SUT 网关前端壳（SPA fallback）——该路径没有真实产物，"
                    "请核对产物路径后重试或如实记录下载失败",
                    details={"url": dest_url},
                )
        except BaseException:
            dest_path.unlink(missing_ok=True)  # 半截文件不留包（孤儿文件防护）
            self._ledger_record("download", "error", started, summary=dest_path.name)
            raise
        self._ledger_record("download", "ok", started, summary=dest_path.name)
        return {
            "status": "success",
            "file": f"output/{dest_path.name}",
            "size_bytes": size,
            "content_type": content_type,
        }

    def _download_destination(
        self, url: str, task_id: str, filename: str | None
    ) -> tuple[str, Path]:
        """解析下载 URL（host 白名单）与落盘目的地（workspace/{task_id}/output/）。"""
        if self.workspace_dir is None:
            raise ToolExecutionError("执行上下文未配置 workspace_dir，无法落盘下载产物")
        if not re.fullmatch(r"[A-Za-z0-9._-]+", task_id):
            raise ToolExecutionError(
                f"非法 task_id（仅允许字母/数字/./_/-）: {task_id!r}",
                details={"task_id": task_id},
            )
        resolved_url = self._resolve_download_url(url)
        name = Path(filename).name if filename else Path(urlparse(resolved_url).path).name
        if not name or name in (".", ".."):
            name = "artifact"  # URL 尾段无文件名（如以 / 结尾）时的兜底名
        dest_dir = self.workspace_dir / task_id / "output"
        dest_dir.mkdir(parents=True, exist_ok=True)
        return resolved_url, dest_dir / name

    def _resolve_download_url(self, url: str) -> str:
        """相对路径拼 base_url（host 恒为 SUT 域）；绝对 URL 做 host 白名单校验。"""
        parsed = urlparse(url)
        if not parsed.netloc:
            base = self.channel.sut.base_url.rstrip("/")
            return f"{base}/{url.lstrip('/')}"
        base_host = (urlparse(self.channel.sut.base_url).hostname or "").lower()
        allowed = {
            base_host,
            *(h.strip().lower() for h in self.channel.sut.artifact_hosts if h.strip()),
        } - {""}
        host = (parsed.hostname or "").lower()
        if host not in allowed:
            raise ToolExecutionError(
                f"下载 URL 越界: host {host!r} 不在白名单（base_url 域 ∪ sut.artifact_hosts）"
                "——SUT 产物仅在配置声明的域内下载",
                details={"host": host, "allowed": sorted(allowed)},
            )
        return url

    async def _stream_download(self, url: str, path: Path) -> tuple[int, str]:
        """流式下载到 path，返回 (字节数, Content-Type)；HTTP 错误/超限即中止。"""
        session = await self.channel.auth.get_session()
        size = 0
        async with self.channel.client.stream(
            "GET", url, headers=session.mount_headers() or None, timeout=self.channel.sut.timeout
        ) as response:
            if response.status_code >= 400:
                raise AgentProtocolError(
                    f"产物下载失败（HTTP {response.status_code}）: {url}",
                    details={"sut": self.channel.sut.name, "status_code": response.status_code},
                )
            content_type = response.headers.get("content-type", "")
            with path.open("wb") as fh:
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > DOWNLOAD_MAX_BYTES:
                        raise ToolExecutionError(
                            f"产物超过单文件大小上限 {DOWNLOAD_MAX_BYTES} 字节，已中止: {url}",
                            details={"url": url, "limit_bytes": DOWNLOAD_MAX_BYTES},
                        )
                    fh.write(chunk)
        return size, content_type

    def _merge_metadata(self, metadata: dict[str, Any] | None) -> dict[str, Any]:
        return {**self.default_metadata, **(metadata or {})}


def _normalize_answer(answer: Any) -> dict[str, Any]:
    """答案规范化：字符串视为单选值；dict 透传（selected 为字符串时包装为列表）。"""
    if isinstance(answer, str):
        return {"selected": [answer]}
    if isinstance(answer, dict):
        normalized = dict(answer)
        if isinstance(normalized.get("selected"), str):
            normalized["selected"] = [normalized["selected"]]
        return normalized
    raise ToolExecutionError(
        f"不支持的反问答案形态: {type(answer).__name__}（应为字符串或 {{selected: [...]}}）"
    )


def _digest_payload(value: Any) -> Any:
    """values/messages 载荷摘要：messages 替换为去 reasoning 的对话骨架。"""
    if isinstance(value, list):
        return compact_messages(value)
    if isinstance(value, dict) and isinstance(value.get("messages"), list):
        shallow = dict(value)
        shallow["messages"] = compact_messages(shallow["messages"])
        return shallow
    return value


def _messages_tail_json(messages: list[dict[str, Any]], budget: int) -> str:
    """消息序列化保尾弃头：预算从最新消息向前分配，历史头部以占位标记省略。

    整表 dumps 再头部截断在多轮线程上会把最新一条 SUT 回复（往往携带产物路径
    或完成声明）挤出窗口——执行 Agent「看不见」交付物便空转催促（run
    20260911_010507 实测：12 次催促烧尽 20 轮，文件路径始终不可见）。最新一条
    无条件保留（compact 后单条文本 ≤ COMPACT_TEXT_MAX_CHARS，预算必然容纳）。
    """
    kept: list[dict[str, Any]] = []
    used = 2  # JSON 数组方括号
    for message in reversed(messages):
        chunk = json.dumps(message, ensure_ascii=False, default=str)
        if kept and used + len(chunk) + 1 > budget:
            break
        kept.insert(0, message)
        used += len(chunk) + 1
    omitted = len(messages) - len(kept)
    if omitted <= 0:
        return json.dumps(kept, ensure_ascii=False, default=str)
    marker = json.dumps({"note": f"（前 {omitted} 条历史消息已省略）"}, ensure_ascii=False)
    return json.dumps([marker, *kept], ensure_ascii=False, default=str)


def _values_tail_json(values: dict[str, Any], budget: int) -> str:
    """values 外壳 + messages 的复合载荷保尾弃头（与消息列表同病同治）。

    values（state 终态）是 {messages: [...], ...} 复合结构——整表 dumps 再
    头部截断同样会把最新一条 SUT 回复挤出窗口，故 messages 用同一保尾预算
    序列化，外壳其余键 dumps 计入预算开销（过半则先头部截断）。
    """
    shell = {k: v for k, v in values.items() if k != "messages"}
    shell_json = json.dumps(shell, ensure_ascii=False, default=str)
    if len(shell_json) > budget // 2:
        shell_json = truncate(shell_json, budget // 2)
    messages_budget = budget - len(shell_json) - 20  # 组合键名/括号序列化开销
    tail = _messages_tail_json(values.get("messages") or [], max(messages_budget, 200))
    combined = {**json.loads(shell_json), "messages": json.loads(tail)}
    return json.dumps(combined, ensure_ascii=False, default=str)


def bounded_result(result: dict[str, Any]) -> dict[str, Any]:
    """截断大体量字段（values/messages 先摘要化再文本化），保留状态与产出物结构。

    消息列表与 values 复合载荷走保尾弃头——最新一条 SUT 回复必须留在
    窗口内；其余字段维持头部截断语义。
    """
    bounded = dict(result)
    for field in ("values", "messages", "text"):
        if field in bounded and bounded[field] is not None:
            if isinstance(bounded[field], str):
                bounded[field] = truncate(bounded[field], VALUES_MAX_CHARS)
                continue
            digest = _digest_payload(bounded[field])
            if isinstance(digest, list):
                bounded[field] = _messages_tail_json(digest, VALUES_MAX_CHARS)
            elif isinstance(digest, dict) and isinstance(digest.get("messages"), list):
                bounded[field] = _values_tail_json(digest, VALUES_MAX_CHARS)
            else:
                bounded[field] = truncate(
                    json.dumps(digest, ensure_ascii=False, default=str), VALUES_MAX_CHARS
                )
    if "error" in bounded and isinstance(bounded["error"], dict):
        message = bounded["error"].get("message")
        if isinstance(message, str):
            bounded["error"]["message"] = truncate(message, VALUES_MAX_CHARS)
    return bounded


__all__ = ["AgentProtocolToolServer"]
