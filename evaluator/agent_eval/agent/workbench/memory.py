"""会话记忆 — 对话要点持久化与跨进程续作消息组装。"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from agent_eval.agent.workbench.types import WorkbenchAgentConfig


def session_key(pkg_root: Path) -> str:
    """会话记录文件名：root 绝对路径摘要 + 目录名。

    草稿续作（``--output`` 指回同一目录）命中同一文件——对话上下文跨进程延续；
    包归位后路径变化自然开新记录。
    """
    import hashlib

    digest = hashlib.sha1(str(pkg_root.resolve()).encode()).hexdigest()[:16]
    return f"{digest}-{pkg_root.name or 'package'}.json"


class SessionStore:
    """对话要点持久化（仅 user/assistant 文本，不含工具流量）。

    同一包目录命中同一记录文件；写入失败不影响会话（同 _log 容错策略）。
    """

    def __init__(self, session_file: Path, *, max_entries: int) -> None:
        self.session_file = session_file
        self.max_entries = max_entries
        self.last_snapshot: dict[str, Any] | None = None
        self.dialogue = self._load()

    def _load(self) -> list[dict[str, str]]:
        self.last_snapshot = None
        try:
            data = json.loads(self.session_file.read_text(encoding="utf-8"))
            dialogue = data.get("dialogue", [])
            snapshot = data.get("snapshot")
            if isinstance(snapshot, dict):
                self.last_snapshot = snapshot
        except (OSError, ValueError):
            return []
        return [d for d in dialogue if isinstance(d, dict) and d.get("role") and d.get("text")]

    def record(
        self, user_text: str, reply: str, root: str, *, snapshot: dict[str, Any] | None = None
    ) -> None:
        """追加本轮对话要点并落盘（超出上限从头部丢弃）。

        ``snapshot`` 为当前进度快照（暂存 + 骨架留档 + 证据账本，调用方组装），
        每轮整体覆写——快照即「当前进度态」而非历史，重启据此续作不丢进度。
        """
        self.dialogue.append({"role": "user", "text": user_text})
        if reply:
            self.dialogue.append({"role": "assistant", "text": reply})
        self.dialogue = self.dialogue[-self.max_entries :]
        if snapshot is not None:
            self.last_snapshot = snapshot
        try:
            self.session_file.parent.mkdir(parents=True, exist_ok=True)
            payload: dict[str, Any] = {
                "root": root,
                "updated": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "dialogue": self.dialogue,
            }
            if self.last_snapshot is not None:
                payload["snapshot"] = self.last_snapshot
            self.session_file.write_text(
                json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
            )
        except OSError:
            pass  # 记录失败不影响会话（同 _log 容错策略）


def resume_messages(
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
