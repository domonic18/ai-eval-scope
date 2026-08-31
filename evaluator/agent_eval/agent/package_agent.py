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
        return (
            template.replace("{tools}", self._describe_tools()).replace(
                "{pkg_root}", str(self.server.root)
            )
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
    ) -> TurnResult:
        """执行一轮：Agent 生成 → 用户确认 → 校验门禁（≤N 回改）→ 落盘/回滚。

        confirm_fn(reply, diff) 由 CLI 注入（全部应用 / 放弃）；放弃时本轮暂存清空
        且消息历史截断回本轮前，保持 Agent 上下文与磁盘/暂存一致。
        """
        self._log("turn_start", instruction=user_text)
        history_len = len(self._messages)
        self._messages.append(("user", user_text))

        state = await self._invoke(self._messages)
        self._messages = list(state.get("messages", self._messages))
        reply = _last_ai_text(self._messages)

        if not self.server.has_staged_changes:
            self._log("turn_end", committed=False, reason="no_changes")
            return TurnResult(reply=reply, diff="", staged=False)

        diff = self.server.render_diff()
        if not confirm_fn(reply, diff):
            self.server.reset_staging()
            del self._messages[history_len:]
            self._log("turn_end", committed=False, reason="user_aborted")
            return TurnResult(reply=reply, diff=diff, staged=True, aborted_reason="user_aborted")

        result = await self._gate_and_commit()
        return TurnResult(
            reply=reply,
            diff=diff,
            staged=True,
            committed=result["committed"],
            committed_files=result.get("files", []),
            validation_errors=result.get("errors", []),
            aborted_reason=result.get("reason", ""),
        )

    async def _gate_and_commit(self) -> dict[str, Any]:
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
            state = await self._invoke(self._messages)
            self._messages = list(state.get("messages", self._messages))
        return {"committed": False, "errors": ["校验轮次耗尽"], "reason": "max_fix_rounds"}

    async def _invoke(self, messages: list[Any]) -> dict[str, Any]:
        """单次图调用（测试注入点：monkeypatch 本方法可脱离 deepagents 回放状态机）。"""
        if self._graph is None:
            self._graph = self._build_graph()
        return await self._graph.ainvoke(
            {"messages": messages},
            config={"recursion_limit": self.max_turns * 2},
        )

    # ─── 首轮模板 ─────────────────────────────────────────────────

    @staticmethod
    def first_turn_text(
        instruction: str, *, new_package: bool = False, ref: str | None = None
    ) -> str:
        """组装首轮用户消息（新建包用 generate_new_package 模板并钉住目标包引用）。"""
        templates: dict[str, str] = _load_prompts()["templates"]
        key = "generate_new_package" if new_package else "first_turn"
        text = templates[key].replace("{instruction}", instruction)
        return text.replace("{ref}", ref) if ref else text

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


def _last_ai_text(messages: list[Any]) -> str:
    """取消息列表中最后一条 AI 文本（计划/总结展示用）。"""
    for msg in reversed(messages):
        text = getattr(msg, "content", "")
        if getattr(msg, "type", "") == "ai" and isinstance(text, str) and text.strip():
            return text.strip()
    return ""


def run_turn(
    agent: PackageAgent, user_text: str, *, confirm_fn: Callable[[str, str], bool]
) -> TurnResult:
    """同步包装（CLI / REPL 调用）。"""
    return asyncio.run(agent.turn(user_text, confirm_fn=confirm_fn))
