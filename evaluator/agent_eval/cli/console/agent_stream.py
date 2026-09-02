"""Agent 工作过程流式渲染（claude code 式直播）— 表现层基础设施。

与 console/prompts、console/render 同层：无业务语义，命令层与向导层双向复用。
事件契约（WorkbenchAgent.turn 的 ``on_event`` 回调，§六）：

- ``token`` / ``thinking``——正文与思考增量（Anthropic 风格 blocks 已在会话机
  拆分），直写终端不解释 markup；思考用暗色斜体
- ``tool_start`` / ``tool_end``——工具行实时可见（首参提示 + 结果行）
- ``tool_args``——大文件内容在 tool_call args 里增量生成的进度（``\\r`` 单行，
  仅 TTY；非 TTY 静默，防管道日志被控制符污染）
- ``phase: checkpoint``——自动分段续跑提示（§6.7 P1）
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from typing import Any

from rich import print as rprint

# 工具行首参提示：start 行只展示最关键参数，其余省略
_TOOL_ARG_HINT = {
    "write_file": "path",
    "read_file": "path",
    "delete_file": "path",
    "read_reference": "ref",
    "search_reference": "query",
}


def _tool_end_line(event: dict[str, Any]) -> str | None:
    """tool_end → 结果行（None = 不渲染）；error 交 Agent 自修复仅黄色提示。"""
    name = event.get("name", "")
    output = event.get("output", "")
    data: dict[str, Any] = {}
    if isinstance(output, str):
        try:
            parsed = json.loads(output)
            data = parsed if isinstance(parsed, dict) else {}
        except ValueError:
            data = {}
    if not event.get("ok", True) or "error" in data:
        detail = data.get("error") or output or "失败"
        return f"  [yellow]⚠ {name}: {str(detail)[:120]}[/yellow]"
    if "staged" in data:
        return f"  [green]✓[/green] [dim]已暂存 {data['staged']}[/dim]"
    if "staged_delete" in data:
        return f"  [green]✓[/green] [dim]已暂存删除 {data['staged_delete']}[/dim]"
    if name == "validate_package":
        return "  [green]✓[/green] [dim]暂存视图校验通过[/dim]"
    if name == "preview_diff":
        return f"  [green]✓[/green] [dim]diff 就绪（{data.get('changed', '?')} 处变更）[/dim]"
    return None


def _write_stream(text: str, style: str | None = None) -> None:
    """流式片段直写：不解释 markup / 不做高亮（模型文本原样），style 用于思考态。"""
    import rich

    rich.get_console().print(text, end="", style=style, markup=False, highlight=False)


def make_stream_emitter() -> tuple[Callable[[dict[str, Any]], None], Callable[[], None]]:
    """流式渲染器：返回 (emit, finish)——emit 收事件，finish 收尾未闭合的行。

    - 段首空白吞掉：模型 text/thinking 段常以 ``\\n\\n`` 开头，直接接头部会出现
      「🤖 后空行」（实测反馈）；
    - 思考 ↔ 正文切换才起行，同模式片段续写不换行；
    - 工具参数生成阶段（大文件内容在 tool_call args 里增量生成，不走 text 流）
      以 ``\\r`` 单行进度显示，避免数十秒无输出的「卡住」观感；仅 TTY。
    """
    tty = sys.stdout.isatty()
    state: dict[str, Any] = {
        "mid_line": False,  # 流式文本行未收尾（需先换行才能打工具行）
        "mode": "",  # "" | text | thinking
        "pend": "",  # 参数生成中的工具名
        "pend_len": 0,
        "pend_shown": False,
    }

    def _clear_pending() -> None:
        if state["pend_shown"]:
            sys.stdout.write("\r\033[K")  # 光标回行首并清行
            sys.stdout.flush()
            state["pend_shown"] = False

    def _close_line() -> None:
        _clear_pending()
        if state["mid_line"]:
            sys.stdout.write("\n")
            sys.stdout.flush()
            state.update(mid_line=False, mode="")

    def _hint(name: str, args: dict[str, Any]) -> str:
        key = _TOOL_ARG_HINT.get(name)
        if not key:
            return ""
        value = args.get(key)
        if isinstance(value, dict):
            value = ",".join(map(str, value)) or ""
        if key == "path" and isinstance(value, str) and value.startswith("/"):
            # 绝对路径只显示文件名——草稿区全路径是会话实现细节，无需反复露出；
            # 相对路径原样展示（保留目录信息）
            value = value.rstrip("/").rsplit("/", 1)[-1]
        elif isinstance(value, str) and len(value) > 72:
            value = "…" + value[-70:]
        return f" · {value}" if value else ""

    def emit(event: dict[str, Any]) -> None:
        kind = event.get("type")
        if kind == "phase" and event.get("name") == "checkpoint":
            _close_line()
            rprint(
                f"[dim]⏭ 单段步数撞线，已自动续跑（第 {event.get('segment')} / "
                f"{event.get('max_segments')} 段，进度保留）[/dim]"
            )
            return
        if kind in ("token", "thinking"):
            mode = "text" if kind == "token" else "thinking"
            text = event.get("text", "")
            if state["mode"] != mode:  # 思考 ↔ 正文切换才起行，片段间续写不换行
                text = text.lstrip("\r\n ")
                if not text:
                    return  # 段首全是空白——等首个有内容的片段再起行
                _close_line()
                rprint(
                    "[dim italic]✻ [/dim italic]"
                    if mode == "thinking"
                    else "[bold cyan]🤖[/bold cyan] ",
                    end="",
                )
                state.update(mid_line=True, mode=mode)
            _write_stream(text, "dim" if mode == "thinking" else None)
            return
        if kind == "tool_args":
            name = event.get("name") or state["pend"]
            if name and name != state["pend"]:
                _clear_pending()
                state.update(pend=name, pend_len=0)
            state["pend_len"] += int(event.get("delta") or 0)
            if tty and name and state["pend_len"]:
                sys.stdout.write(f"\r  ⏳ {name} 生成参数中 · {state['pend_len']} 字")
                sys.stdout.flush()
                state["pend_shown"] = True
            return
        _close_line()
        state.update(pend="", pend_len=0)
        if kind == "tool_start":
            rprint(
                f"  [dim]🔧 {event.get('name', '')}{_hint(event.get('name', ''), event.get('args') or {})}[/dim]"
            )
        elif kind == "tool_end":
            line = _tool_end_line(event)
            if line:
                rprint(line)

    return emit, _close_line
