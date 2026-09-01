"""PackageAgent — 场景包工程会话 Agent（arch/15 §六，REPL 式）。

用户在 CLI 中持续输入自然语言（``你> ...``），Agent 经沙盒工具面改包、
宿主展示 diff 并确认、校验门禁通过后落盘——多轮会话共享消息历史与暂存区
（Agent 记得之前的改动上下文）。

会话流程（每轮 :meth:`turn`）::

    你> <自然语言需求>
      → ainvoke（Agent 输出计划 → 调工具写暂存 → 自检 preview_diff）
      → 宿主 confirm_fn(reply, diff)：False = 回滚本轮（暂存清空 + 历史截断）
      → validate_package 门禁：失败则把 errors 注入下一轮回改（≤ max_fix_rounds）
      → commit() 原子落盘 + 会话日志

底座：复用 DeepAgents（``create_deep_agent`` + ``build_chat_model``，arch/03 §3.2）；
不挂 checkpointer（会话历史由宿主持有重放）；预算以 recursion_limit 约束
（BudgetGuard 回调接入留待逐任务预算需求出现时）。
"""

from __future__ import annotations

import asyncio
import functools
import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from agent_eval.agent.package_tools import PackageToolServer
from agent_eval.core.exceptions import AgentError

_PROMPTS_PATH = (
    Path(__file__).resolve().parent.parent / "assets" / "configs" / ("package_agent_prompts.yaml")
)

# ref 缺省时的拟定指引（Agent 按需求起名，用户可在会话中自然语言改）
_REF_AGENT_CHOSEN = (
    "未指定——请根据评测需求拟定（小写英文与连字符，语义贴合需求），"
    "并在改动计划第一行明确给出「拟定引用: <scenario/id>」"
)


@functools.lru_cache(maxsize=1)
def _load_prompts() -> dict[str, Any]:
    """加载 package_agent_prompts.yaml → {system_prompt, templates}。"""
    try:
        data = yaml.safe_load(_PROMPTS_PATH.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as e:
        raise AgentError(
            f"PackageAgent 提示词资产损坏: {_PROMPTS_PATH}（{e}）",
            details={"path": str(_PROMPTS_PATH)},
        ) from e
    if not isinstance(data, dict) or not data.get("system_prompt") or not data.get("templates"):
        raise AgentError(
            f"PackageAgent 提示词资产结构不完整（需 system_prompt/templates）: {_PROMPTS_PATH}",
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


class PackageAgent:
    """场景包工程会话 Agent（一个实例 = 一次 REPL 会话，跨轮共享历史与暂存）。"""

    def __init__(
        self,
        pkg_root: Path,
        *,
        llm_role: str = "agent",
        max_turns: int = 40,
        max_fix_rounds: int = 3,
        log_dir: Path | None = None,
    ) -> None:
        from agent_eval.config.paths import paths

        self.server = PackageToolServer(Path(pkg_root))
        self.llm_role = llm_role
        self.max_turns = max_turns
        self.max_fix_rounds = max_fix_rounds
        self._messages: list[Any] = []
        self._graph: Any | None = None
        self._log_path = (
            log_dir
            or paths.default_workspace
            / "agent_logs"
            / f"package_agent_{time.strftime('%Y%m%d_%H%M%S')}.jsonl"
        )

    # ─── 组装 ─────────────────────────────────────────────────────

    def _describe_tools(self) -> str:
        return "\n".join(f"- {s.name}: {s.description}" for s in PackageToolServer.TOOL_SPECS)

    def _build_system_prompt(self) -> str:
        # 字面 replace 而非 str.format：提示词是散文体，含 { type: ... } 等
        # 字面大括号示例，format 会误当占位符吞掉
        template: str = _load_prompts()["system_prompt"]
        return template.replace("{tools}", self._describe_tools()).replace(
            "{pkg_root}", str(self.server.root)
        )

    def _build_graph(self) -> Any:
        """组装 DeepAgents 图（deepagents / langchain 为 [agent] extra，惰性导入）。"""
        try:
            from deepagents import create_deep_agent
        except ImportError:
            raise AgentError(
                "PackageAgent 需要 deepagents（DeepAgents 底座，见 arch/15 §六）。"
                "请执行: uv sync --extra agent",
                details={"missing_module": "deepagents"},
            ) from None
        from agent_eval.agent.model_bridge import build_chat_model

        tools = self.server.to_langchain_tools()
        return create_deep_agent(
            model=build_chat_model(self.llm_role),
            tools=tools,
            system_prompt=self._build_system_prompt(),
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

        confirm_fn(reply, diff) 由 CLI 注入（全部应用 / 放弃）；放弃时本轮暂存清空
        且消息历史截断回本轮前，保持 Agent 上下文与磁盘/暂存一致。
        on_event 收流式进度事件（``token`` / ``tool_start`` / ``tool_end`` / ``phase``），
        CLI 据此直播工作过程；None = 静默。
        中断（Ctrl+C）或异常同样回滚暂存并截断历史后原样上抛——磁盘从未见过本轮内容。
        """
        self._log("turn_start", instruction=user_text)
        history_len = len(self._messages)
        self._messages.append(("user", user_text))
        try:
            state = await self._invoke(self._messages, on_event=on_event)
            self._messages = list(state.get("messages", self._messages))
            reply = _last_ai_text(self._messages)

            if not self.server.has_staged_changes:
                self._log("turn_end", committed=False, reason="no_changes")
                return TurnResult(reply=reply, diff="", staged=False)

            diff = self.server.render_diff()
            if on_event:
                on_event({"type": "phase", "name": "confirm"})
            if not confirm_fn(reply, diff):
                self.server.reset_staging()
                del self._messages[history_len:]
                self._log("turn_end", committed=False, reason="user_aborted")
                return TurnResult(
                    reply=reply, diff=diff, staged=True, aborted_reason="user_aborted"
                )

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
        except BaseException:
            self.server.reset_staging()
            del self._messages[history_len:]
            raise

    async def _gate_and_commit(
        self, on_event: Callable[[dict[str, Any]], None] | None = None
    ) -> dict[str, Any]:
        """校验门禁：失败注入错误回改（≤ max_fix_rounds），通过则原子落盘。"""
        templates: dict[str, str] = _load_prompts()["templates"]
        for round_no in range(1, self.max_fix_rounds + 1):
            validation = await self.server.validate_package()
            if validation["ok"]:
                files = self.server.commit()
                self._log("commit", files=files)
                return {"committed": True, "files": files}
            errors = validation["errors"]
            self._log("validate_failed", round=round_no, errors=errors)
            if round_no == self.max_fix_rounds:
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
        config = {"recursion_limit": self.max_turns * 2}
        if on_event is None:
            result: dict[str, Any] = await self._graph.ainvoke(
                {"messages": messages}, config=config
            )
            return result
        final: dict[str, Any] = {}
        async for mode, payload in self._graph.astream(
            {"messages": messages},
            config=config,
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
        return final or await self._graph.ainvoke({"messages": messages}, config=config)

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
    agent: PackageAgent,
    user_text: str,
    *,
    confirm_fn: Callable[[str, str], bool],
    on_event: Callable[[dict[str, Any]], None] | None = None,
) -> TurnResult:
    """同步包装（CLI / REPL 调用）。"""
    return asyncio.run(agent.turn(user_text, confirm_fn=confirm_fn, on_event=on_event))
