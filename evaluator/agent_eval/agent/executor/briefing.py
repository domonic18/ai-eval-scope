"""决策简报聚合器（arch/16 §5.1 P5）——把机械壳已掌握的现实喂给决策体。

简报素材全部来自机械壳（账本 ``remaining``/``budget_digest`` + 证据台账 +
SUT 状态观察 + ``last_run`` 摘要），决策体不自行拼凑现实——喂什么看什么，
是仲裁质量的上界（arch/16 §5.1）。三件套：

- :class:`SutStateTracker`：观察时间线——每次 SUT 状态采证记一笔快照，
  摘要不变即「空闲」计时增长。观察语义纯机械：我们看到的 SUT 状态
  **何时停止变化**，不猜 SUT 内部（谓词裁决权在决策体，见 §5.2）。
- :func:`extract_artifact_candidates`：从 SUT 文本中提取产物路径/链接候选。
- :func:`build_briefing`：聚合为每轮注入的简报 dict（尺寸有硬上限——
  简报是每轮上下文税，不设防会吃掉工具结果的窗口）。

不做 turns_left（保险丝对用户不可见，arch/16 §九.2）与 baseline
（SUT 画像是 Phase 3）。
"""

from __future__ import annotations

import re
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from agent_eval.agent.executor.ledger import ResourceLedger

# 观察点保尾条数（idle 判定只关心「最近是否变化」，全历史无价值）
_TRACKER_MAX_OBSERVATIONS = 20
# 简报各文本槽位上限（整体硬上限的组成部分，bytes 级可预算）
_CANDIDATE_MAX_CHARS = 120
_ACTIVITY_MAX_CHARS = 60
_DIGEST_MAX_CHARS = 200
_INSTRUCTION_MAX_CHARS = 80
# 产物候选上限条数
_CANDIDATES_LIMIT = 5
# 简报引用的台账事件条数（活动时间线）
_ACTIVITY_EVENTS = 3

# 完成仲裁受控枚举（arch/16 §5.2 P2）——「SUT 完成了吗」由决策体按简报仲裁，
# unknown 是合法出口：证据冲突时保守等待，机械超时兜底（误判完成产空包 vs
# 误判未完成多等一个周期，代价不对称）
ARBITRATION_VERDICTS = ("complete", "progressing", "stalled", "unknown")

# 产物路径/URL 候选：含路径分隔符且内嵌文档扩展名的非空白 token，整段截取
# （查询串 ?q=1 一并保留——截掉会让下载候选不可用）。双前置 lookahead 定资格，
# token 本体贪婪到空白/标点边界；字符类排除空白与中英文常用标点
_ARTIFACT_TOKEN = r"[^\s\"'<>，。；、！？：（）()【】\[\]]"
_ARTIFACT_RE = re.compile(
    rf"(?={_ARTIFACT_TOKEN}*[/])"
    rf"(?={_ARTIFACT_TOKEN}*\.(?:pdf|docx?|pptx?|xlsx?|md|zip|png|jpe?g|html?|csv))"
    rf"{_ARTIFACT_TOKEN}{{1,200}}",
    re.IGNORECASE,
)


@dataclass
class SutStateTracker:
    """SUT 状态观察时间线（随任务生灭，跨任务不串）。

    digest 用摘要文本直接比对（而非 hash）：values 体量经调用方截断后
    直比成本可忽略，省一层编码。``last_change_ts`` = 当前摘要首次出现
    的时刻；``idle_for_s`` = 距该时刻的时长。
    """

    observations: deque[dict[str, Any]] = field(default_factory=deque)
    last_change_ts: float | None = None

    def observe(self, busy: bool, values_text: str) -> None:
        """记录一次 SUT 状态观察；摘要变化即刷新「最后变化时刻」。"""
        now = time.monotonic()
        self.observations.append({"ts": now, "busy": busy, "digest": values_text})
        if len(self.observations) > _TRACKER_MAX_OBSERVATIONS:
            self.observations.popleft()
        if self.last_change_ts is None or values_text != self.observations[-2]["digest"]:
            self.last_change_ts = now

    def idle_for_s(self) -> float | None:
        """当前状态已持续秒数；观察不足两次（无法界定「持续」）返回 None。"""
        if self.last_change_ts is None or len(self.observations) < 2:
            return None
        return time.monotonic() - self.last_change_ts

    @property
    def last_busy(self) -> bool | None:
        """最近一次观察的 busy 标记；无观察返回 None。"""
        if not self.observations:
            return None
        return bool(self.observations[-1]["busy"])

    @property
    def last_values_text(self) -> str:
        """最近一次观察的摘要原文（产物候选提取素材）；无观察返回空串。"""
        if not self.observations:
            return ""
        return str(self.observations[-1]["digest"])


def extract_artifact_candidates(texts: list[str]) -> list[str]:
    """从 SUT 文本中提取产物路径/链接候选（去重保序，截 ``_CANDIDATES_LIMIT`` 条）。"""
    seen: set[str] = set()
    candidates: list[str] = []
    for text in texts:
        if not text:
            continue
        for match in _ARTIFACT_RE.findall(text):
            token = match.rstrip(".,;:")
            if token not in seen:
                seen.add(token)
                candidates.append(token[:_CANDIDATE_MAX_CHARS])
            if len(candidates) >= _CANDIDATES_LIMIT:
                return candidates
    return candidates


def instruction_digest(input: Any) -> str:
    """从转发给 SUT 的 input 提取指令摘要（str 直取；dict 取 instruction/首个字符串值）。"""
    if isinstance(input, str):
        text = input
    elif isinstance(input, dict):
        text = str(input.get("instruction") or "")
        if not text:
            text = next((str(v) for v in input.values() if isinstance(v, str) and v.strip()), "")
    else:
        text = ""
    return text.strip()


def _activity_line(ledger: ResourceLedger) -> str:
    """近 N 条台账事件渲染为单行活动时间线（「时刻 动作 结果」→ 拼接）。"""
    evidence = ledger.evidence
    if evidence is None:
        return ""
    parts: list[str] = []
    for event in list(evidence.events)[-_ACTIVITY_EVENTS:]:
        clock = event.get("ts", "").split("T")[-1][:8]  # ISO 时分秒 HH:MM:SS
        line = f"{clock} {event.get('action', event.get('kind', '?'))} {event.get('outcome', '')}"
        parts.append(line.strip()[:_ACTIVITY_MAX_CHARS])
    return " → ".join(parts)


def _hint(
    tracker: SutStateTracker | None, candidates: list[str], last_run: dict[str, Any] | None
) -> str:
    """仲裁事实速览（纯事实拼装，不含谓词猜测——裁决是决策体的事）。"""
    facts: list[str] = []
    idle = tracker.idle_for_s() if tracker else None
    if idle is not None:
        facts.append(f"观察到的状态已 {idle:.0f}s 未变化")
    if candidates:
        facts.append(f"产物候选 {len(candidates)} 项")
    pending = (last_run or {}).get("pending")
    if pending:
        facts.append(f"待答反问 {len(pending.get('questions') or [])} 题")
    return "；".join(facts) if facts else "尚无 SUT 状态观察"


def build_briefing(
    *,
    ledger: ResourceLedger,
    tracker: SutStateTracker | None,
    last_run: dict[str, Any] | None,
) -> dict[str, Any]:
    """聚合机械壳既有事实为决策简报（每动作后刷新，随工具结果注入）。

    各额度形如「剩余/上限」（决策关心的是还能做什么）；``last_run.text``
    与 ``input`` 由工具注册表回填，input 经 :func:`instruction_digest`
    还原为转发指令原文。
    """
    last_run = last_run or {}
    candidates = extract_artifact_candidates(
        [str(last_run.get("text") or ""), tracker.last_values_text if tracker else ""]
    )
    elapsed = ledger.budget_digest()[-1]
    return {
        "objective": instruction_digest(last_run.get("input"))[:_INSTRUCTION_MAX_CHARS],
        "resources": {
            "sut_calls": ledger.remaining("sut_call"),
            "nudges": ledger.remaining("nudge"),
            "state_polls": ledger.remaining("state_poll"),
            "downloads": ledger.remaining("download"),
            "elapsed_s": round(float(elapsed.get("used_s") or 0)),
            "wall_remaining_s": max(
                round(float(elapsed.get("limit") or 0) - float(elapsed.get("used_s") or 0)), 0
            ),
        },
        "sut_state": {
            "thread_busy": tracker.last_busy if tracker else None,
            "idle_for_s": (
                round(idle_s)
                if tracker is not None and (idle_s := tracker.idle_for_s()) is not None
                else None
            ),
            "pending_questions": len(((last_run.get("pending") or {}).get("questions")) or []),
            "artifact_candidates": candidates,
            "activity": _activity_line(ledger),
        },
        "arbitration": {
            "hint": _hint(tracker, candidates, last_run),
            "standard": (
                "按系统提示仲裁标准判定 complete/progressing/stalled/unknown，"
                "结论经 read_thread_state(verdict=…)/run_on_thread(rationale=…) 落台账"
            ),
        },
        "last_result_digest": str(last_run.get("text") or "")[:_DIGEST_MAX_CHARS],
    }


__all__ = [
    "ARBITRATION_VERDICTS",
    "SutStateTracker",
    "build_briefing",
    "extract_artifact_candidates",
    "instruction_digest",
]
