"""Agent Hooks — 预算控制与结构化日志（arch/03 §7a、§3.6）。

BudgetController 监控 Agent 执行成本（token/美元计量 + 硬性上限）；
SessionLogger 将 Agent 执行全程输出为机器可解析的 JSON Lines
（workspace/runs/{run_id}/agent_logs/）。两者经 LangGraph 回调
（agent/callbacks.py 的 BudgetGuard / SessionLogCallback）注入执行流程。
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# 单条日志 output 摘要截断上限（字符）
OUTPUT_SUMMARY_MAX_CHARS = 500

# 输入摘要脱敏关键词（命中即值替换为 "***"）
_SENSITIVE_KEY_MARKS = ("api_key", "apikey", "token", "secret", "password", "authorization")


def _now_iso() -> str:
    """当前 UTC 时间的 ISO 8601 表示。"""
    return datetime.now(UTC).isoformat()


def _summarize(value: Any, max_chars: int = 500) -> Any:
    """生成工具输入/输出的脱敏摘要（用于结构化日志，arch/03 §7a.3）。"""
    if isinstance(value, dict):
        return {
            k: (
                "***"
                if any(m in k.lower() for m in _SENSITIVE_KEY_MARKS)
                else _summarize(v, max_chars)
            )
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_summarize(v, max_chars) for v in value[:20]]
    if isinstance(value, str):
        if len(value) <= max_chars:
            return value
        return f"{value[:max_chars]}...（已截断，共 {len(value)} 字符）"
    return value


@dataclass
class AgentExecutionLog:
    """Agent 执行的结构化日志条目（arch/03 §7a.3）。"""

    # 追踪信息
    timestamp: str
    run_id: str
    task_id: str
    trace_id: str

    # 事件类型: agent_start | tool_call | tool_result | agent_decision | agent_end | error
    event: str

    # 工具调用（event=tool_call / tool_result 时）
    tool_call_id: str | None = None
    tool_name: str | None = None
    tool_input_summary: dict[str, Any] | None = None
    tool_output_summary: dict[str, Any] | None = None
    tool_duration_ms: float | None = None
    tool_status: str | None = None  # "success" | "error" | "timeout"

    # Agent 决策（event=agent_decision 时）
    decision: str | None = None  # "retry" | "fallback" | "skip" | "continue"
    decision_reason: dict[str, Any] | str | None = None

    # 成本追踪
    cost_usd: float = 0.0
    tokens_used: int = 0
    turns_used: int = 0

    # 错误信息（event=error 时）
    error_type: str | None = None
    error_message: str | None = None


@dataclass
class _PendingCall:
    """待匹配的工具调用（tool_call → tool_result 配对）。"""

    tool_name: str
    started: float


class BudgetController:
    """预算控制器，监控 Agent 执行成本（arch/03 §3.6）。

    check() 状态机：spent < 80% → "ok"；80%~100% → "warning"；≥ 上限 → "exceeded"。
    """

    def __init__(self, max_budget_usd: float, warn_threshold: float = 0.8) -> None:
        self.max_budget_usd = max_budget_usd
        self.warn_threshold = warn_threshold
        self.spent_usd: float = 0.0
        self.total_tokens: int = 0

    def record(self, cost_usd: float = 0.0, tokens: int = 0) -> str:
        """累计一次计量（LLM 回调的 token/成本），返回最新状态。"""
        self.spent_usd += cost_usd
        self.total_tokens += tokens
        return self.check()

    def check(self) -> str:
        """检查当前预算状态。

        Returns:
            "ok" | "warning" | "exceeded"
        """
        if self.max_budget_usd <= 0:
            return "ok"
        if self.spent_usd >= self.max_budget_usd:
            return "exceeded"
        if self.spent_usd >= self.max_budget_usd * self.warn_threshold:
            return "warning"
        return "ok"


class SessionLogger:
    """Agent 执行会话的结构化日志记录器（arch/03 §7a.2-7a.5）。

    每个任务一个 JSONL 文件（agent_{task_id}.jsonl），close() 时向
    agent_summary.jsonl 追加一条汇总。所有事件同时保留在内存 events 列表，
    便于上层直接消费（如构建 trace/metrics）。
    """

    def __init__(
        self,
        run_id: str,
        task_id: str,
        log_dir: Path | str | None = None,
        *,
        trace_id: str | None = None,
    ) -> None:
        """初始化 SessionLogger。

        Args:
            run_id: 运行 ID（一次 run_task_set 共享）。
            task_id: 任务 ID。
            log_dir: 日志目录；缺省为 ./workspace/runs/{run_id}/agent_logs。
            trace_id: 追踪 ID；缺省自动生成。
        """
        self.run_id = run_id
        self.task_id = task_id
        self.trace_id = trace_id or uuid.uuid4().hex[:12]
        self.log_dir = (
            Path(log_dir)
            if log_dir is not None
            else Path("./workspace/runs") / run_id / "agent_logs"
        )
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = self.log_dir / f"agent_{task_id}.jsonl"

        self.events: list[AgentExecutionLog] = []
        self._pending: dict[str, _PendingCall] = {}
        self.started_at: str = ""
        self.finished_at: str = ""
        self.tool_call_count = 0
        self.error_count = 0
        self.total_cost_usd = 0.0
        self.total_tokens = 0
        self.turns_used = 0
        self._closed = False
        self._t0 = 0.0

    # ─── 事件记录 API ───

    def log_start(
        self,
        task_input: dict[str, Any] | None = None,
        task_constraints: dict[str, Any] | None = None,
    ) -> None:
        """记录 agent_start 事件（会话起点）。"""
        self.started_at = _now_iso()
        self._t0 = time.perf_counter()
        reason: dict[str, Any] = {}
        if task_input is not None:
            reason["task_input"] = _summarize(task_input)
        if task_constraints is not None:
            reason["task_constraints"] = _summarize(task_constraints)
        self._emit("agent_start", decision_reason=reason or None)

    def log_tool_call(self, tool_name: str, tool_input: dict[str, Any]) -> str:
        """记录 tool_call 事件，返回 call_id（供 log_tool_result 配对）。"""
        call_id = uuid.uuid4().hex[:12]
        self._pending[call_id] = _PendingCall(tool_name=tool_name, started=time.perf_counter())
        self._emit(
            "tool_call",
            tool_call_id=call_id,
            tool_name=tool_name,
            tool_input_summary=_summarize(tool_input) if tool_input else {},
        )
        return call_id

    def log_tool_result(
        self,
        tool_name: str,
        output: dict[str, Any] | None,
        call_id: str | None = None,
        *,
        status: str = "success",
        duration_ms: float | None = None,
    ) -> None:
        """记录 tool_result 事件（含耗时与状态）。"""
        pending = self._pending.pop(call_id, None)
        if duration_ms is None and pending is not None:
            duration_ms = (time.perf_counter() - pending.started) * 1000
        self._emit(
            "tool_result",
            tool_call_id=call_id,
            tool_name=tool_name,
            tool_output_summary=_summarize(output or {}, OUTPUT_SUMMARY_MAX_CHARS),
            tool_duration_ms=round(duration_ms, 3) if duration_ms is not None else None,
            tool_status=status,
        )

    def log_decision(self, decision: str, reason: dict[str, Any] | None = None) -> None:
        """记录 agent_decision 事件（retry / fallback / skip / continue）。"""
        self._emit("agent_decision", decision=decision, decision_reason=_summarize(reason or {}))

    def log_error(self, error_type: str, message: str) -> None:
        """记录 error 事件。"""
        self.error_count += 1
        self._emit("error", error_type=error_type, error_message=message)

    def log_end(
        self,
        cost_usd: float = 0.0,
        tokens_used: int = 0,
        turns_used: int = 0,
    ) -> None:
        """记录 agent_end 事件（会话终点，含成本汇总）。"""
        self.finished_at = _now_iso()
        self.total_cost_usd += cost_usd
        self.total_tokens += tokens_used
        self.turns_used = max(self.turns_used, turns_used)
        self._emit(
            "agent_end",
            cost_usd=round(self.total_cost_usd, 6),
            tokens_used=self.total_tokens,
            turns_used=self.turns_used,
        )

    def close(self) -> Path:
        """向 agent_summary.jsonl 追加本任务汇总，返回汇总文件路径。"""
        summary_path = self.log_dir / "agent_summary.jsonl"
        if self._closed:
            return summary_path
        self._closed = True
        duration_ms = (time.perf_counter() - self._t0) * 1000 if self._t0 else 0.0
        summary = {
            "timestamp": _now_iso(),
            "run_id": self.run_id,
            "task_id": self.task_id,
            "trace_id": self.trace_id,
            "event": "agent_summary",
            "events": len(self.events),
            "tool_calls": self.tool_call_count,
            "errors": self.error_count,
            "cost_usd": round(self.total_cost_usd, 6),
            "tokens_used": self.total_tokens,
            "turns_used": self.turns_used,
            "duration_ms": round(duration_ms, 3),
            "log_file": str(self.log_path),
        }
        with summary_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(summary, ensure_ascii=False) + "\n")
        return summary_path

    # ─── 内部 ───

    def _emit(self, event: str, **fields: Any) -> None:
        """构建日志条目：追加到内存列表并落盘一行 JSON。"""
        entry = AgentExecutionLog(
            timestamp=_now_iso(),
            run_id=self.run_id,
            task_id=self.task_id,
            trace_id=self.trace_id,
            event=event,
            **fields,
        )
        if event == "tool_call":
            self.tool_call_count += 1
        self.events.append(entry)
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(entry), ensure_ascii=False, default=str) + "\n")
