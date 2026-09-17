"""Agent 工作过程流式渲染（claude code 式直播）— 表现层基础设施。

与 console/prompts、console/render 同层：无业务语义，命令层与向导层双向复用。
事件契约（WorkbenchAgent.turn 的 ``on_event`` 回调，§六）：

- ``token`` / ``thinking``——正文与思考增量（Anthropic 风格 blocks 已在会话机
  拆分）。正文 TTY 下行缓冲经 markdown-lite 渲染（完整行才转换，部分行挂起至
  收行兜底；非 TTY 保持原样直写，管道日志机器可读）；思考用暗色斜体原样直写
- ``tool_start`` / ``tool_end``——工具行实时可见（首参提示 + 结果行）
- ``tool_args``——大文件内容在 tool_call args 里增量生成的进度（``\\r`` 单行，
  仅 TTY；非 TTY 静默，防管道日志被控制符污染）
- ``todos``——Agent 任务清单更新（write_todos 工具落状态后提取），与上次相同
  则不重复渲染
- ``phase: checkpoint``——自动分段续跑提示（§6.7 P1）
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from typing import Any

from rich import print as rprint
from rich.text import Text

from agent_eval.cli.console.markdown_lite import MarkdownLite

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


def _print_text(item: Text | str) -> None:
    """渲染 Text（自带 span 样式）/ 纯串：不解释 markup、不做自动高亮。"""
    import rich

    rich.get_console().print(item, end="", markup=False, highlight=False)


def _print_line(item: Text | str, *, markup: bool = False) -> None:
    """整行渲染（带换行）：任务清单等成块输出；不自动高亮防数字被误染色。"""
    import rich

    rich.get_console().print(item, markup=markup, highlight=False)


# 任务清单图标与条目样式（status → 图标/样式；in_progress 加粗突出当前项）
_TODO_ICONS: dict[str, tuple[str, str]] = {
    "completed": ("✓", "green"),
    "in_progress": ("▶", "bold cyan"),
    "pending": ("○", "dim"),
}
_TODO_STYLES: dict[str, str | None] = {
    "completed": "dim strike",
    "in_progress": "bold",
    "pending": None,
}


def make_stream_emitter() -> tuple[Callable[[dict[str, Any]], None], Callable[[], None]]:
    """流式渲染器：返回 (emit, finish)——emit 收事件，finish 收尾未闭合的行。

    - 段首空白吞掉：模型 text/thinking 段常以 ``\\n\\n`` 开头，直接接头部会出现
      「🤖 后空行」（实测反馈）；
    - 段尾换行挂账：正文流结尾的 ``\\n`` 不立即落笔——同模式续写时补写（保留
      段落间隔），工具行 / 模式切换前丢弃（实测反馈：工具行与上方正文间空隙）；
    - 思考 ↔ 正文切换才起行，同模式片段续写不换行；
    - 正文 TTY 下行缓冲（``_queue_text``）：完整行经 markdown-lite 渲染，部分行
      挂起至收行（工具行 / 模式切换 / finish）兜底；非 TTY 原样直写；
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
        "tail_nl": 0,  # 正文流尾部已收到、尚未落笔的换行数（挂账）
        "buf": "",  # 正文行缓冲：未收到换行的部分行（仅 TTY 正文模式）
        "md": None,  # MarkdownLite 实例（围栏状态跨行保留；模式切换即弃）
        "last_todos": None,  # 上次渲染的任务清单指纹（去重）
    }

    def _clear_pending() -> None:
        if state["pend_shown"]:
            sys.stdout.write("\r\033[K")  # 光标回行首并清行
            sys.stdout.flush()
            state["pend_shown"] = False

    def _paint(line: str) -> None:
        """一行文本经 markdown-lite 渲染（围栏状态跨行保留在 state["md"]）。"""
        if state["md"] is None:
            state["md"] = MarkdownLite()
        _print_text(state["md"].feed_line(line))
        state["mid_line"] = True

    def _flush_buf() -> None:
        """部分行兜底渲染：工具行 / 模式切换不打断正文，剩余缓冲先落笔。"""
        buf, state["buf"] = state["buf"], ""
        if buf.strip():
            sys.stdout.write("\n" * state["tail_nl"])  # 挂账的段落间隔此刻补写
            state["tail_nl"] = 0
            _paint(buf.rstrip("\r"))

    def _emit_line(line: str) -> None:
        line = line.rstrip("\r")
        if not line.strip():
            state["tail_nl"] += 1  # 空行 = 段落间隔，挂账（同上：续写补、收行弃）
            return
        sys.stdout.write("\n" * state["tail_nl"])  # 此前挂账的空行此刻补写
        state["tail_nl"] = 0
        _paint(line)
        sys.stdout.write("\n")  # 行终止符：行缓冲消费掉的 \n 在此补回
        sys.stdout.flush()
        state["mid_line"] = False  # 完整行已收尾：工具行可直接起行，无需 close 补 \n

    def _close_line() -> None:
        _clear_pending()
        _flush_buf()
        state["tail_nl"] = 0  # 尾部换行丢弃：工具行紧邻正文，不留空隙
        state["md"] = None  # 围栏状态不跨段（工具行 / 模式切换处重置）
        if state["mid_line"]:
            # 完整行已自带终止符（_emit_line），此处只补部分行的换行
            sys.stdout.write("\n")
            sys.stdout.flush()
            state["mid_line"] = False
        state["mode"] = ""  # 模式复位与 mid_line 解耦：完整行后工具事件也要重起头部

    def _write_text(text: str, style: str | None) -> None:
        pending, body = state["tail_nl"], text.rstrip("\r\n")
        state["tail_nl"] = len(text) - len(body)
        if body:
            sys.stdout.write("\n" * pending)  # 同模式续写：此前挂账的段落间隔此刻补写
            _write_stream(body, style)

    def _queue_text(text: str) -> None:
        """正文行缓冲（仅 TTY）：完整行经 markdown-lite 渲染，部分行挂起。"""
        state["buf"] += text
        while "\n" in state["buf"]:
            line, _, rest = state["buf"].partition("\n")
            state["buf"] = rest
            _emit_line(line)

    def _render_todos(todos: list[Any]) -> None:
        """任务清单渲染：✓ 完成 / ▶ 进行中 / ○ 待办；与上次相同则跳过。

        内容经 Text 构建不经 markup 解析——模型写入的 todo 文案可能含 ``[``。
        """
        key = tuple(
            (str(t.get("content", "")), str(t.get("status", "")))
            for t in todos
            if isinstance(t, dict)
        )
        if key == state["last_todos"]:
            return
        state["last_todos"] = key
        done = sum(1 for _, status in key if status == "completed")
        _print_line(f"[dim]📋 任务清单 {done}/{len(key)}[/dim]", markup=True)
        for content, status in key:
            icon, icon_style = _TODO_ICONS.get(status, ("○", "dim"))
            line = Text("  ")
            line.append(icon, style=icon_style)
            line.append(" ")
            if content:
                line.append(content, style=_TODO_STYLES.get(status))
            _print_line(line)

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
            if mode == "text" and tty:
                _queue_text(text)  # 行缓冲 markdown-lite；非 TTY 保持原样直写
            else:
                _write_text(text, "dim" if mode == "thinking" else None)
            return
        if kind == "todos":
            _close_line()
            _render_todos(event.get("todos") or [])
            return
        if kind == "tool_args":
            _close_line()  # 进度行独占一行：正文行先收尾（尾部换行已挂账，恰补一个换行）
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
