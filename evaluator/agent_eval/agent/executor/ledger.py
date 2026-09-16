"""资源账本与证据台账（arch/16 §4.3-4.4 P3+P4-a）。

ResourceLedger —— 机械壳的额度仲裁者：预算消耗归机器，不靠提示词自觉。
``authorize`` 在工具入口仲裁额度（消耗即记账，与调用成败无关——尝试语义），
拒绝时返回带 guidance 的结构化载荷（BudgetExhausted 模式，闸门即指引）；
``record`` 只补记结果证据。判定逻辑全部收在本模块，工具入口只做 3-4 行委托。

EvidenceLedger —— 语义层证据台账（独立于 SessionLogger 的传输层日志）：
append-only 事件流，随执行包落 ``ledger.jsonl``，失败包凭它回答
「SUT 干了什么 / 执行器决定了什么 / 为什么」三问。
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agent_eval.execution.models import InteractionPolicy

_SUMMARY_MAX_CHARS = 200
# 连拒升级阈值：同 action 连续被拒达此次数，拒绝载荷点名收尾路径（Phase 2.1）
_REFUSAL_ESCALATION_THRESHOLD = 3
_REFUSAL_ESCALATION_ACTION = "write_package"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _truncate(value: Any) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return text[:_SUMMARY_MAX_CHARS]


class EvidenceLedger:
    """语义证据台账 —— append-only 事件流，dump 为执行包内 ledger.jsonl。

    事件 kind：sut_call / state_poll / gate_refusal / artifact / close /
    decision（P2 决策简报预留，本期不产生）。
    """

    KINDS = ("sut_call", "state_poll", "gate_refusal", "artifact", "close", "decision")

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def log(self, kind: str, **fields: Any) -> dict[str, Any]:
        """追加一条证据事件（kind 见 KINDS，未知 kind 原样保留不拦截）。"""
        event = {"kind": kind, "ts": _now_iso(), **fields}
        self.events.append(event)
        return event

    def dump(self, package_dir: Path) -> Path:
        """落盘 ledger.jsonl（每行一个 JSON 事件），返回文件路径。"""
        package_dir.mkdir(parents=True, exist_ok=True)
        path = package_dir / "ledger.jsonl"
        lines = [json.dumps(e, ensure_ascii=False) for e in self.events]
        path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
        return path


# 动作 → 额度字段映射；前三个动作同时消耗 sut_calls_total（合计面）
_ACTION_LIMIT_FIELD = {
    "dispatch": "dispatch",
    "nudge": "nudges",
    "sut_call": "sut_calls_total",
    "state_poll": "state_polls",
    "download": "downloads",
}
_ACTIONS_WITH_TOTAL = ("dispatch", "nudge", "sut_call")
# 动作 → 证据事件 kind
_ACTION_EVIDENCE_KIND = {
    "dispatch": "sut_call",
    "nudge": "sut_call",
    "sut_call": "sut_call",
    "state_poll": "state_poll",
    "download": "artifact",
}

# 额度耗尽的闸门指引（拒绝即指引——LLM 按此行动而非自行发挥）
_GUIDANCE = {
    "sut_calls_total": (
        "SUT 交互总额已用尽。停止发起调用：先 read_thread_state 取证，"
        "有产物走 download_sut_file 收集后 write_package(success=true)，"
        "无产物 write_package(success=false, error=完整证据) 收尾。"
    ),
    "dispatch": (
        "新会话首发额度已用尽。先 read_thread_state 取证确认 SUT 是否已有产出："
        "有产物走 download_sut_file 收集后 write_package(success=true)，"
        "无产物 write_package(success=false, error=完整证据) 收尾。"
    ),
    "nudges": (
        "催促额度已用尽，停止继续催促。先 read_thread_state 取证，"
        "再按产物有无 write_package 收尾（success=false 时 error 写完整证据）。"
    ),
    "state_polls": "取证轮询额度已用尽。基于已掌握的信息 write_package 收尾。",
    "downloads": (
        "下载额度已用尽。以 read_thread_state 中的产物路径/清单作为证据 write_package 收尾。"
    ),
}


def uninjected_ledger_refusal(action: str) -> dict[str, Any]:
    """账本未注入时的 fail-closed 拒绝载荷（AI 审查硬化项，run 20260913_064226）。

    「无账本」不能等于「无额度」：装配链遗漏 _inject_ledger 时闸门收紧而非
    静默放行（放行即对被测系统无限额探测口）。载荷与 BudgetExhausted 同构，
    LLM 无需感知差异；无 evidence 可落 gate_refusal——链路缺失本身即证据。
    """
    return {
        "status": "failed",
        "error": {
            "type": "BudgetExhausted",
            "budget": "ledger_missing",
            "action": action,
            "message": "资源账本未注入（fail-closed 兜底拒绝）——执行器装配可能遗漏账本",
            "guidance": (
                "这是装配缺陷而非正常额度耗尽，重试同样会被拒。基于已掌握的信息 "
                "write_package 收尾（success=false，error 写明本拒绝）。"
            ),
        },
    }


class ResourceLedger:
    """单任务资源账本 —— 交互预算的仲裁与记账（随任务生灭，不跨任务复用）。"""

    def __init__(
        self,
        policy: InteractionPolicy,
        evidence: EvidenceLedger | None = None,
    ) -> None:
        self.policy = policy
        self.evidence = evidence
        self.counters: dict[str, int] = dict.fromkeys(_ACTION_LIMIT_FIELD, 0)
        self.task_started_at = _now_iso()
        self.last_nudge_at: float | None = None
        self.refusals: list[dict[str, Any]] = []
        self._started_monotonic = time.monotonic()

    # ─── 额度仲裁 ───

    def authorize(self, action: str) -> dict[str, Any] | None:
        """仲裁动作额度：放行返回 None（并记账），拒绝返回结构化载荷。

        拒绝不消耗额度（含 backoff 窗口期——它是节奏信号，不是额度耗尽）。
        """
        limit_field = _ACTION_LIMIT_FIELD.get(action)
        if limit_field is None:
            raise ValueError(f"未知预算动作: {action!r}（合法: {sorted(_ACTION_LIMIT_FIELD)}）")

        wall = self._wall_clock_refusal()
        if wall is not None:
            return self._refuse(action, wall)

        if action in _ACTIONS_WITH_TOTAL:
            total_refusal = self._limit_refusal(
                action, "sut_calls_total", self.counters["sut_call"], self.policy.sut_calls_total
            )
            if total_refusal is not None:
                return self._refuse(action, total_refusal)

        limit = getattr(self.policy, limit_field)
        used = self.counters[action]
        refusal = self._limit_refusal(action, limit_field, used, limit)
        if refusal is not None:
            return self._refuse(action, refusal)

        last_nudge = self.last_nudge_at
        if action == "nudge" and last_nudge is not None and not self._nudge_backoff_elapsed():
            wait_s = self.policy.nudge_backoff_s - (time.monotonic() - last_nudge)
            return self._refuse(
                action,
                {
                    "budget": "nudge_backoff",
                    "used": used,
                    "limit": limit,
                    "message": (
                        f"距上次催促不足 {self.policy.nudge_backoff_s:.0f} 秒"
                        f"（还需等待约 {max(wait_s, 0):.0f} 秒）"
                    ),
                    "guidance": (
                        "这是节奏窗口而非额度耗尽，本次不消耗催促额度。先 read_thread_state "
                        "取证检查 SUT 是否已有新产出；确需再次催促，先做其他取证动作消耗时间。"
                    ),
                },
            )

        # 放行并记账（尝试语义：与调用成败无关）；nudge 记录节奏锚点。
        # sut_call 的自键即合计面（_ACTION_LIMIT_FIELD 指向 sut_calls_total），
        # 勿再叠加；dispatch/nudge 另记各自的分类面
        self.counters[action] = used + 1
        if action in ("dispatch", "nudge"):
            self.counters["sut_call"] += 1
        if action == "nudge":
            self.last_nudge_at = time.monotonic()
        return None

    def record(
        self,
        action: str,
        outcome: str,
        duration_s: float | None = None,
        summary: Any = None,
    ) -> None:
        """补记动作结果证据（authorize 已记账，这里只落证据流）。"""
        if self.evidence is None:
            return
        fields: dict[str, Any] = {"action": action, "outcome": outcome}
        if duration_s is not None:
            fields["duration_s"] = round(duration_s, 3)
        if summary is not None:
            fields["summary"] = _truncate(summary)
        self.evidence.log(_ACTION_EVIDENCE_KIND[action], **fields)

    # ─── 视图 ───

    def remaining(self, action: str) -> str:
        """剩余额度视图（"2/3" 形态）——决策简报素材。"""
        limit_field = _ACTION_LIMIT_FIELD.get(action)
        if limit_field is None:
            raise ValueError(f"未知预算动作: {action!r}")
        limit = getattr(self.policy, limit_field)
        return f"{max(limit - self.counters[action], 0)}/{limit}"

    def budget_digest(self) -> list[dict[str, Any]]:
        """预算摘要（拒绝载荷与失败包用）：各额度 used/limit + 墙钟。"""
        digest = [
            {
                "budget": limit_field,
                "used": self.counters[action],
                "limit": getattr(self.policy, limit_field),
            }
            for action, limit_field in _ACTION_LIMIT_FIELD.items()
        ]
        digest.append(
            {
                "budget": "wall_clock",
                "used_s": round(time.monotonic() - self._started_monotonic, 1),
                "limit": self.policy.wall_clock_deadline_s,
            }
        )
        return digest

    # ─── 内部 ───

    def _wall_clock_refusal(self) -> dict[str, Any] | None:
        elapsed = time.monotonic() - self._started_monotonic
        if elapsed <= self.policy.wall_clock_deadline_s:
            return None
        return {
            "budget": "wall_clock",
            "used": round(elapsed, 1),
            "limit": self.policy.wall_clock_deadline_s,
            "message": (
                f"任务墙钟预算已耗尽（已用时 {elapsed:.0f}s / "
                f"上限 {self.policy.wall_clock_deadline_s:.0f}s）"
            ),
            "guidance": (
                "立即停止新的 SUT 交互：read_thread_state 快速取证后 write_package 收尾"
                "（成功与否基于已有产物判断）。"
            ),
        }

    def _limit_refusal(
        self, action: str, limit_field: str, used: int, limit: int
    ) -> dict[str, Any] | None:
        if used < limit:
            return None
        return {
            "budget": limit_field,
            "used": used,
            "limit": limit,
            "message": f"预算 {limit_field} 已用尽（{used}/{limit}，动作 {action}）",
            "guidance": _GUIDANCE[limit_field],
        }

    def _nudge_backoff_elapsed(self) -> bool:
        if self.last_nudge_at is None:
            return True
        return time.monotonic() - self.last_nudge_at >= self.policy.nudge_backoff_s

    def _refuse(self, action: str, error: dict[str, Any]) -> dict[str, Any]:
        self.register_refusal(action, error)
        payload: dict[str, Any] = {
            "status": "failed",
            "error": {"type": "BudgetExhausted", **error},
            "ledger_digest": self.budget_digest(),
        }
        if self.evidence is not None:
            self.evidence.log("gate_refusal", action=action, **error)
        return payload

    # ─── 连拒升级（Phase 2.1：重放显示 13 连拒零依从，空转要被点名） ───

    def _refusal_streak(self, action: str) -> int:
        """尾部连续同 action 拒绝次数（被其它动作打断则清零重计）。"""
        streak = 0
        for entry in reversed(self.refusals):
            if entry.get("action") != action:
                break
            streak += 1
        return streak

    def register_refusal(self, action: str, error: dict[str, Any]) -> str | None:
        """登记一次闸门拒绝并返回升级语（尾部连拒 ≥3 时非 None）。

        额度闸（``_refuse``）与资格闸（如催促缺 rationale）共用：拒绝不消耗
        额度，但同 action 连续被拒说明模型在空转——升级语直接点名收尾路径，
        且就地写进 error（随拒绝载荷与证据流一并可见）。
        """
        self.refusals.append({"action": action, "error": error})
        streak = self._refusal_streak(action)
        if streak < _REFUSAL_ESCALATION_THRESHOLD:
            return None
        escalation = (
            f"同一动作（{action}）已被连续拒绝 {streak} 次——重复同样的调用不会成功，"
            f"立即按 guidance 收尾（{_REFUSAL_ESCALATION_ACTION}）。"
        )
        error["escalation"] = escalation
        return escalation
