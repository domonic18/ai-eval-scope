"""WorkbenchAgent — 评测工作台会话 Agent（arch/15 §六，REPL 式）。

对标 Claude Code 的形态：通用会话机 + 按域装配的工具面（profile，D-WB-2）——
场景包工程（含 SUT 接入调试）是首个装配域，新域 = 新工具面 + 新提示词段，会话机不动。

用户在 CLI 中持续输入自然语言（``你> ...``），Agent 经沙盒工具面改包、
宿主展示 diff 并确认、校验门禁通过后落盘——多轮会话共享消息历史与暂存区
（Agent 记得之前的改动上下文）；对话要点持久化到 ``workspace/agent_sessions/``，
草稿续作（新进程）时自动注入此前对话，跨会话不失忆。

会话流程（每轮 :meth:`turn`）::

    你> <自然语言需求>
      → ainvoke（Agent 输出计划 → 调工具写暂存 → 自检 preview_diff）
        ↳ recursion_limit 撞线 → 自动开新段续跑（≤ max_segments，checkpoint 事件）
      → 宿主 confirm_fn(reply, diff)：False = 回滚本轮（暂存清空，对话保留）
      → validate_package 门禁：失败则把 errors 注入下一轮回改（≤ max_fix_rounds）
      → commit() 原子落盘 + 会话日志

失败语义（§6.7 D-WB-4）：**唯一的失败是用户放弃**。撞线分段耗尽 / Ctrl+C 中断 /
LLM 瞬时错误 / 预算到界一律 = 暂停保现场——salvage 捞检查点半途消息（孤儿
tool_call 合成失败 ToolMessage）并入历史，暂存不动，用户可「继续」接着干或
显式「放弃」（:meth:`abandon_pending`，唯一回滚触发器）。

底座：复用 DeepAgents（``create_deep_agent`` + ``build_chat_model``，arch/03 §3.2）；
成功路径仍由宿主持有消息重放，内存检查点（MemorySaver）仅作事故现场保存器；
BudgetGuard 会话级预算（budget_usd 启用）到线同样走暂停。
"""

from __future__ import annotations

import asyncio
import functools
import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

from agent_eval.agent.callbacks import BudgetGuard
from agent_eval.agent.sut_probe_tools import PROBE_TIMEOUT_S, TOOL_BUDGETS, SUTProbeToolServer
from agent_eval.agent.workbench_tools import PackageToolServer
from agent_eval.config.paths import PACKAGE_ROOT, paths
from agent_eval.core.exceptions import AgentError, BudgetExceededError
from agent_eval.execution.auth.credentials import CredentialStore

try:  # langgraph 属 [agent] extra；缺席（CI 纯单测）时撞线判定恒 False
    from langgraph.errors import GraphRecursionError as _GraphRecursionError
except ImportError:  # pragma: no cover
    _GraphRecursionError = None  # type: ignore[assignment,misc]


def _is_recursion_limit(exc: BaseException) -> bool:
    """recursion_limit 撞线判定（langgraph 缺席时恒 False）。"""
    return _GraphRecursionError is not None and isinstance(exc, _GraphRecursionError)


# salvage 合成的失败 ToolMessage 正文（同时告知模型该调用未完成，可重发）
_ORPHAN_TOOL_NOTE = "（会话在此被打断，未执行完——如仍需该结果请重新调用）"


def _synthetic_tool_message(call_id: str, name: str) -> Any:
    """构造孤儿 tool_call 的失败 ToolMessage（langchain_core 缺席时退化占位对象）。"""
    try:
        from langchain_core.messages import ToolMessage
    except ImportError:  # pragma: no cover — 单测 mock 环境
        from types import SimpleNamespace

        return SimpleNamespace(
            type="tool", tool_call_id=call_id, name=name, content=_ORPHAN_TOOL_NOTE
        )
    return ToolMessage(content=_ORPHAN_TOOL_NOTE, tool_call_id=call_id, name=name)


def repair_orphan_tool_calls(messages: list[Any]) -> list[Any]:
    """半途消息的孤儿 tool_call 修复：无结果的调用合成失败 ToolMessage。

    当年「历史不完整就整段截断」的真实原因是孤儿 tool_call 会破坏图（AI 发起
    调用后没有配对 ToolMessage，下次调模型 API 直接 400）——salvage 并入宿主
    历史前必须补齐，进度才真正可续。
    """
    repaired = list(messages)
    pending: dict[str, str] = {}  # tool_call_id → name（含序）
    for msg in repaired:
        mtype = getattr(msg, "type", "")
        if mtype == "ai":
            for call in getattr(msg, "tool_calls", None) or []:
                call_id = str(call.get("id", "") if isinstance(call, dict) else "")
                if call_id:
                    pending[call_id] = str(call.get("name", "") if isinstance(call, dict) else "")
        elif mtype == "tool":
            pending.pop(str(getattr(msg, "tool_call_id", "")), None)
    repaired.extend(_synthetic_tool_message(call_id, name) for call_id, name in pending.items())
    return repaired


_PROMPTS_PATH = PACKAGE_ROOT / "assets" / "configs" / "workbench_agent_prompts.yaml"

# ref 缺省时的拟定指引（Agent 按需求起名，用户可在会话中自然语言改）
_REF_AGENT_CHOSEN = (
    "未指定——请根据评测需求拟定（小写英文与连字符，语义贴合需求），"
    "并在改动计划第一行明确给出「拟定引用: <scenario/id>」"
)


@dataclass(frozen=True, slots=True)
class WorkbenchAgentConfig:
    """会话机可调参数（arch/15 §6.11.2：tunables 单点载体）。

    默认值是安全阀不是天花板；§6.7 P2 的 CLI 旗标
    （``--max-turns/--max-segments/--budget-usd``）以本对象为同一载体注入。
    """

    max_turns: int = 40  # 单段安全阀基数（recursion_limit = max_turns × 2，非任务预算）
    max_fix_rounds: int = 3  # 校验门禁回改轮上限
    max_segments: int = 3  # 自动分段续跑上限（§6.7 P1；撞线即开新段直到此数）
    budget_usd: float | None = None  # 会话预算（§6.7 P2；None = 不启用）
    max_dialogue_entries: int = 40  # 持久化的对话条数上限（防跨会话无限膨胀）
    resume_max_entries: int = 24  # 续作注入上下文的最多条数
    resume_max_chars: int = 400  # 续作注入单条截断
    # 探测域档位默认（D-WB-2 域 = 工具面 + 提示词段 + 门禁策略，域档位可覆盖）
    probe_budgets: dict[str, int] = field(default_factory=lambda: dict(TOOL_BUDGETS))
    probe_timeout_s: float = PROBE_TIMEOUT_S


def _session_key(pkg_root: Path) -> str:
    """会话记录文件名：root 绝对路径摘要 + 目录名。

    草稿续作（``--output`` 指回同一目录）命中同一文件——对话上下文跨进程延续；
    包归位后路径变化自然开新记录。
    """
    import hashlib

    digest = hashlib.sha1(str(pkg_root.resolve()).encode()).hexdigest()[:16]
    return f"{digest}-{pkg_root.name or 'package'}.json"


def _base_url_host(base_url: str) -> str:
    """从 sut.base_url 提取主机（支持 ``${VAR:-https://host}`` env 缺省形态）。"""
    if match := re.search(r":-(.+?)\}", base_url):
        base_url = match.group(1)
    candidate = base_url if "//" in base_url else f"https://{base_url}"
    return (urlparse(candidate).hostname or "").lower()


def _resume_messages(
    dialogue: list[dict[str, str]], config: WorkbenchAgentConfig
) -> list[tuple[str, str]]:
    """把持久化的此前对话组装为注入消息（user 记录 + assistant 应答确认）。

    只重放对话要点（用户输入与最终回复），不重放工具调用流量——文件内容
    以当前包内实际文件为准（回滚/落盘差异由提示言明，防 Agent 误判）。
    """
    lines = []
    for d in dialogue[-config.resume_max_entries :]:
        who = "用户" if d.get("role") == "user" else "助手"
        text = str(d.get("text", ""))
        if len(text) > config.resume_max_chars:
            text = text[: config.resume_max_chars] + "…"
        lines.append(f"{who}: {text}")
    context = (
        "（续接此前会话——以下是本场景包先前对话的记录，其中用户给出的信息与讨论结论仍有效：\n"
        + "\n".join(lines)
        + "\n——记录结束。请在此基础上继续，勿重复追问已给出的信息；"
        "此前提到的文件内容以当前包内实际文件为准）"
    )
    return [("user", context), ("assistant", "已了解此前会话记录，将继续完成场景包工作。")]


@functools.lru_cache(maxsize=1)
def _load_prompts() -> dict[str, Any]:
    """加载 workbench_agent_prompts.yaml。

    结构（D-WB-2 域 = 提示词段 + 工具面 + 门禁策略）：
    ``system_prompt_base``（会话机段，零域语义）/ ``domain_segments.*``（域段）/
    ``domain_labels.*``（域展示名）/ ``templates``（首轮与回改模板）。
    """
    try:
        data = yaml.safe_load(_PROMPTS_PATH.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as e:
        raise AgentError(
            f"WorkbenchAgent 提示词资产损坏: {_PROMPTS_PATH}（{e}）",
            details={"path": str(_PROMPTS_PATH)},
        ) from e
    required = ("system_prompt_base", "domain_segments", "templates")
    if not isinstance(data, dict) or any(not data.get(k) for k in required):
        raise AgentError(
            f"WorkbenchAgent 提示词资产结构不完整（需 {'/'.join(required)}）: {_PROMPTS_PATH}",
            details={"path": str(_PROMPTS_PATH)},
        )
    return data


@dataclass
class TurnResult:
    """单轮会话结果（宿主据此渲染与续轮）。"""

    reply: str  # Agent 计划/总结文本
    diff: str  # 暂存 vs 磁盘统一 diff
    staged: bool  # 本轮是否产生了暂存变更
    committed: bool = False  # 是否已落盘
    committed_files: list[str] = field(default_factory=list)
    validation_errors: list[str] = field(default_factory=list)  # 最终仍未修复的错误
    aborted_reason: str = ""  # 用户放弃 / 轮次耗尽等


class WorkbenchAgent:
    """工作台会话 Agent（一个实例 = 一次 REPL 会话，跨轮共享历史与暂存）。

    ``domain`` 为域档位（缺省场景包域）：选择提示词段；工具面当前固定为
    包域文件沙盒 + SUT 探测，随域路线图（§6.9）扩展为按档位装配。
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
        self.domain = domain  # 域档位：选择提示词段（工具面装配随域扩展，§6.8）
        self.server = PackageToolServer(Path(pkg_root), ask_fn=ask_fn)
        # SUT 接入调试工具面（arch/15 §6.6）：与文件沙盒并列；凭证域隔离到密钥区
        self.probe = SUTProbeToolServer(
            ask_fn=ask_fn,
            credential_store=CredentialStore(),
            budgets=self.config.probe_budgets,
            timeout_s=self.config.probe_timeout_s,
            log_path=None,  # 探测证据随 agent_logs 统一落盘，见 _log_path
        )
        self.llm_role = llm_role
        self._messages: list[Any] = []
        # 失控缰绳（§6.7）：预算护栏会话级累计（跨段/跨轮不清零）；内存检查点
        # 仅作事故现场保存器（成功路径宿主持有消息重放，架构不变）
        self._budget_guard = BudgetGuard(self.config.budget_usd) if self.config.budget_usd else None
        self._checkpointer: Any = None  # 惰性创建（langgraph 属 [agent] extra）
        self._call_seq = 0
        self._last_thread_id = ""
        # 会话记忆持久化（跨进程续作）：同一包目录命中同一记录文件
        self._session_file = (
            paths.default_workspace / "agent_sessions" / _session_key(Path(pkg_root))
        )
        self._dialogue: list[dict[str, str]] = self._load_dialogue()
        self._graph: Any | None = None
        self._log_path = (
            log_dir
            or paths.default_workspace
            / "agent_logs"
            / f"workbench_agent_{time.strftime('%Y%m%d_%H%M%S')}.jsonl"
        )
        self.probe.log_path = self._log_path  # 探测证据与会话日志同文件（时间线完整）

    # ─── 会话记忆（跨进程续作） ────────────────────────────────────

    def _load_dialogue(self) -> list[dict[str, str]]:
        try:
            data = json.loads(self._session_file.read_text(encoding="utf-8"))
            dialogue = data.get("dialogue", [])
        except (OSError, ValueError):
            return []
        return [d for d in dialogue if isinstance(d, dict) and d.get("role") and d.get("text")]

    @property
    def resumed_dialogue_count(self) -> int:
        """已续接的此前会话对话条数（0 = 全新会话），宿主据此显示续作提示。"""
        return len(self._dialogue)

    def _record_turn(self, user_text: str, reply: str) -> None:
        """记录本轮对话要点并持久化（仅 user/assistant 文本，不含工具流量）。"""
        self._dialogue.append({"role": "user", "text": user_text})
        if reply:
            self._dialogue.append({"role": "assistant", "text": reply})
        self._dialogue = self._dialogue[-self.config.max_dialogue_entries :]
        try:
            self._session_file.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "root": str(self.server.root),
                "updated": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "dialogue": self._dialogue,
            }
            self._session_file.write_text(
                json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
            )
        except OSError:
            pass  # 记录失败不影响会话（同 _log 容错策略）

    # ─── 组装 ─────────────────────────────────────────────────────

    def _describe_tools(self) -> str:
        specs = [*PackageToolServer.TOOL_SPECS, *SUTProbeToolServer.TOOL_SPECS]
        return "\n".join(f"- {s.name}: {s.description}" for s in specs)

    def _build_system_prompt(self) -> str:
        """分段装配：会话机段（base）+ 当前域档位的域段（D-WB-2）。"""
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
                "WorkbenchAgent 需要 deepagents（DeepAgents 底座，见 arch/15 §六）。"
                "请执行: uv sync --extra agent",
                details={"missing_module": "deepagents"},
            ) from None
        from langgraph.checkpoint.memory import MemorySaver

        from agent_eval.agent.model_bridge import build_chat_model

        # P0 salvage（§6.7）：内存检查点无 IO、实例销毁即释放；v4.6.3 摘除的是
        # 文件版检查器全量读写空转，内存版无此问题
        self._checkpointer = MemorySaver()
        tools = self.server.to_langchain_tools() + self.probe.to_langchain_tools()
        return create_deep_agent(
            model=build_chat_model(self.llm_role),
            tools=tools,
            system_prompt=self._build_system_prompt(),
            checkpointer=self._checkpointer,
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
        撞线/中断/瞬时错误/预算到界 = 暂停保现场（§6.7 D-WB-4）：salvage 捞检查点
        半途消息并入历史、暂存不动——分段未耗尽时自动续跑（P1），否则上抛或以
        aborted_reason=segment_limit/budget_exceeded 交还宿主（进度完整）。
        """
        self._log("turn_start", instruction=user_text)
        self.probe.new_turn()  # 重置 SUT 探测轮内预算（arch/15 §6.6 总量约束）
        if not self._messages and self._dialogue:  # 跨进程续作：注入此前对话要点
            self._messages.extend(_resume_messages(self._dialogue, self.config))
        self._messages.append(("user", user_text))
        segment = 1
        while True:  # 自动分段续跑（§6.7 P1）：同一对话/预算池/暂存，撞线开新段
            try:
                state = await self._invoke(self._messages, on_event=on_event)
                break
            except BaseException as exc:  # noqa: BLE001 — 统一暂停语义（D-WB-4）
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

    # ─── 暂停与续作（§6.7：唯一的失败是用户放弃） ──────────────────

    async def _salvage_halfway(self) -> list[Any] | None:
        """撞线/中断后从检查点捞半途消息（孤儿 tool_call 已修复）；无现场返回 None。"""
        if self._graph is None or not self._last_thread_id:
            return None
        try:
            snap = await self._graph.aget_state(
                {"configurable": {"thread_id": self._last_thread_id}}
            )
            messages = list((snap.values or {}).get("messages") or []) if snap else []
        except Exception:  # noqa: BLE001 — salvage 尽力而为，失败不掩盖原异常
            return None
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
        """用户显式放弃暂停轮的暂存改动（D-WB-4 的唯一回滚触发器入口）。"""
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
            errors = [*validation["errors"], *self._sut_protocol_gate()]
            if not errors:
                files = self.server.commit()
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

    def _sut_protocol_gate(self) -> list[str]:
        """落盘门禁：声明 agent_protocol 通道的 sut_config 必须有 probe_protocol 实测。

        实测教训：创建会话把全部预算花在登录攻克后，未做协议探测就把入口页面域
        写进 base_url（protocol_flavor 从参照包继承），执行时 commands 端点 404。
        红线从提示升级为门禁——协议形态与地址必须是本会话的验证结论才允许落盘。
        """
        probed = self.probe.protocol_hosts
        errors: list[str] = []
        for rel, content in sorted(self.server.view().items()):
            if not rel.startswith("sut_configs/") or not rel.endswith((".yaml", ".yml")):
                continue
            try:
                data = yaml.safe_load(content) or {}
            except yaml.YAMLError:
                continue  # 语法错误由 validate_package 上报
            sut = data.get("sut") or {}
            if str(sut.get("channel", "")).lower() != "agent_protocol":
                continue
            host = _base_url_host(str(sut.get("base_url", "")))
            if host and host not in probed:
                errors.append(
                    f"{rel} 声明 channel: agent_protocol，但 base_url 的主机 {host} "
                    "本会话未经 probe_protocol 实测（协议形态与地址必须是验证过的结论）。"
                    "请先调用 probe_protocol(base_url=…) 探测该主机并按 ✅ 端点写 "
                    "protocol_flavor；探测不通则与用户确认正确的接口域后再写配置"
                )
        return errors

    async def _invoke(
        self,
        messages: list[Any],
        *,
        on_event: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        """单次图调用（测试注入点：monkeypatch 本方法可脱离 deepagents 回放状态机）。

        on_event 给定时改走流式（langgraph astream 三模）：``messages`` 增量 token、
        ``updates`` 工具调用/结果、``values`` 收集最终状态；静默路径仍为一次性 ainvoke。
        """
        if self._graph is None:
            self._graph = self._build_graph()
        # langgraph 运行时配置：单段安全阀（P1 降格，非任务预算）；每次调用独立
        # thread_id——检查点仅作本调用的事故现场保存器，成功路径行为不变
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
        final: dict[str, Any] = {}
        async for mode, payload in self._graph.astream(
            {"messages": messages},
            config=runtime_config,
            stream_mode=["messages", "updates", "values"],
        ):
            if mode == "messages":
                chunk = payload[0] if isinstance(payload, tuple) else payload
                # 增量 chunk 的 type 为 "AIMessageChunk"（完整消息才是 "ai"）——实测
                if getattr(chunk, "type", "") not in ("ai", "AIMessageChunk"):
                    continue
                # 工具参数生成阶段（大文件内容在 args 里，不走 text/thinking）——
                # 用户实测曾在此「卡住」数十秒无任何输出，发增量事件供宿主显示进度
                for tc in getattr(chunk, "tool_call_chunks", None) or []:
                    frag = tc.get("args") if isinstance(tc, dict) else getattr(tc, "args", "")
                    on_event(
                        {
                            "type": "tool_args",
                            "name": (tc.get("name") if isinstance(tc, dict) else "") or "",
                            "delta": len(frag or ""),
                        }
                    )
                content = getattr(chunk, "content", "")
                if isinstance(content, str):
                    if content:
                        on_event({"type": "token", "text": content})
                    continue
                # Anthropic 风格 content blocks：text 段走 token，thinking 段独立事件
                for block in content if isinstance(content, list) else []:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") == "text" and block.get("text"):
                        on_event({"type": "token", "text": str(block["text"])})
                    elif block.get("type") == "thinking" and block.get("thinking"):
                        on_event({"type": "thinking", "text": str(block["thinking"])})
            elif mode == "updates" and payload:
                _emit_tool_events(payload, on_event)
            elif mode == "values" and isinstance(payload, dict):
                final = payload
        return final or await self._graph.ainvoke({"messages": messages}, config=runtime_config)

    # ─── 自我介绍（§6.10 横幅：资产化，CLI 只渲染不写死） ────────────

    def intro_text(self) -> str:
        """渲染启动横幅文案（{root}/{domains} 字面 replace；资产无 intro 段返回空）。"""
        prompts = _load_prompts()
        intro = prompts.get("intro")
        if not intro:
            return ""
        label = prompts.get("domain_labels", {}).get(self.domain, self.domain)
        return intro.replace("{root}", str(self.server.root)).replace("{domains}", label)

    # ─── 首轮模板 ─────────────────────────────────────────────────

    @staticmethod
    def first_turn_text(
        instruction: str, *, new_package: bool = False, ref: str | None = None
    ) -> str:
        """组装首轮用户消息（新建包用 generate_new_package 模板）。

        ref 给定时钉住目标引用（Agent 不得自拟）；缺省时指引 Agent 按需求拟定
        并在计划首行明确给出（用户可自然语言改）。
        """
        templates: dict[str, str] = _load_prompts()["templates"]
        key = "generate_new_package" if new_package else "first_turn"
        return (
            templates[key]
            .replace("{instruction}", instruction)
            .replace("{ref}", ref if ref else _REF_AGENT_CHOSEN)
        )

    # ─── 会话日志 ─────────────────────────────────────────────────

    def _log(self, event: str, **payload: Any) -> None:
        try:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            record = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "event": event, **payload}
            with self._log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        except OSError:
            pass  # 日志失败不影响会话（NF-C-03）

    @property
    def log_path(self) -> Path:
        return self._log_path


def _text_from_content(content: Any) -> str:
    """content → 纯文本：str 原样；Anthropic 风格 content blocks 只取 type=text 段。

    KIMI / Claude 系模型 content 为 ``[{"type": "thinking"|"text", ...}, ...]`` 列表
    （thinking 段不并入回复文本）。
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            str(block.get("text", ""))
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
    return ""


def _last_ai_text(messages: list[Any]) -> str:
    """取消息列表中最后一条 AI 文本（计划/总结展示用）。"""
    for msg in reversed(messages):
        text = _text_from_content(getattr(msg, "content", ""))
        if getattr(msg, "type", "") == "ai" and text.strip():
            return text.strip()
    return ""


def _emit_tool_events(updates: dict[str, Any], emit: Callable[[dict[str, Any]], None]) -> None:
    """把 langgraph ``updates`` 增量转成工具进度事件（tool_start / tool_end）。

    - model 节点 AIMessage.tool_calls → tool_start（name + args）
    - tools 节点 ToolMessage → tool_end（ok + 原始输出串，CLI 自行解析 error/staged）
    """
    for delta in updates.values():
        if not isinstance(delta, dict):
            continue
        for msg in delta.get("messages") or []:
            mtype = getattr(msg, "type", "")
            if mtype == "ai":
                for call in getattr(msg, "tool_calls", None) or []:
                    emit(
                        {
                            "type": "tool_start",
                            "name": call.get("name", ""),
                            "args": call.get("args") or {},
                        }
                    )
            elif mtype == "tool":
                content = getattr(msg, "content", "")
                status = getattr(msg, "status", "success")
                emit(
                    {
                        "type": "tool_end",
                        "name": getattr(msg, "name", "") or "",
                        "ok": status != "error",
                        "output": content if isinstance(content, str) else str(content),
                    }
                )


def run_turn(
    agent: WorkbenchAgent,
    user_text: str,
    *,
    confirm_fn: Callable[[str, str], bool],
    on_event: Callable[[dict[str, Any]], None] | None = None,
) -> TurnResult:
    """同步包装（CLI / REPL 调用）。"""
    return asyncio.run(agent.turn(user_text, confirm_fn=confirm_fn, on_event=on_event))
