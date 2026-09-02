"""场景包 Agent 会话入口 — REPL 式自然语言改包（arch/15 §六，requirement F-C-SCN-AGENT）。

用户在 CLI 持续输入自然语言（``你> ...``），PackageAgent 经沙盒工具面改包，工作
过程**流式直播**（claude code 式：回复 token 直出 + 工具调用行实时可见）；每轮展示
diff → 确认（全部应用/放弃）→ 校验门禁 → 原子落盘。空行退出会话，Ctrl+C 中断当前轮
（暂存与历史回滚，磁盘不受影响）。非交互形态（CI）需 ``--instruction`` +
``--yes --trust-agent`` 双开关。
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import typer
from rich import print as rprint

from agent_eval.cli.console.prompts import ask, select

__all__ = ["agent_edit_package", "agent_new_package"]

# 工具行首参提示：start 行只展示最关键参数，其余省略
_TOOL_ARG_HINT = {
    "write_file": "path",
    "read_file": "path",
    "delete_file": "path",
    "read_reference": "ref",
    "search_reference": "query",
}


def _render_diff(diff: str, max_lines: int = 80) -> None:
    rprint("[dim]── diff（暂存 vs 磁盘）──[/dim]")
    for line in diff.splitlines()[:max_lines]:
        color = "green" if line.startswith("+") else ("red" if line.startswith("-") else "")
        rprint(f"[{color}]{line}[/{color}]" if color else line)


def _render_outcome(result: Any) -> None:  # noqa: ANN001 — TurnResult
    if result.committed:
        rprint(f"[green]✅ 已落盘[/green]（{len(result.committed_files)} 个文件变更）")
    elif result.aborted_reason == "user_aborted":
        rprint("[yellow]↩️ 已放弃本轮（磁盘未受影响）[/yellow]")
    elif result.validation_errors:
        rprint("[red]❌ 校验未通过（未落盘）:[/red]")
        for e in result.validation_errors:
            rprint(f"  • {e}")
    elif not result.staged:
        rprint("[yellow]（本轮无文件变更——可继续描述需求或换种说法）[/yellow]")


def _render_turn(reply: str, result: Any) -> None:  # noqa: ANN001 — 非流式兜底渲染
    if reply:
        lines = reply.splitlines()
        rprint(f"[bold cyan]🤖 {lines[0]}[/bold cyan]")
        for line in lines[1:6]:
            rprint(f"   [dim]{line}[/dim]")
    if result.diff:
        _render_diff(result.diff)
    _render_outcome(result)


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


def _make_stream_emitter() -> tuple[Callable[[dict[str, Any]], None], Callable[[], None]]:
    """流式渲染器（claude code 式）：思考/回复 token 直出；工具行实时可见。

    - 段首空白吞掉：模型 text/thinking 段常以 ``\\n\\n`` 开头，直接接头部会出现
      「🤖 后空行」；
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


def _stream_pair() -> tuple[Callable[[dict[str, Any]], None], Callable[[], None]] | None:
    """流式开关：JSON 模式下 stdout 仅 JSON（F-C-INTEG-02），返回 None 走静默路径。"""
    from agent_eval.cli.console.output import is_json

    return None if is_json() else _make_stream_emitter()


def _run_one(agent: Any, text: str) -> None:  # noqa: ANN001 — PackageAgent
    """执行并渲染一轮：流式直播（回复不重复打印）或非流式兜底。"""
    from agent_eval.agent.package_agent import run_turn

    emit, finish = _stream_pair() or (None, None)
    if emit:
        rprint("[dim]⏳ Agent 工作中（流式输出，Ctrl+C 中断本轮）…[/dim]")
    try:
        result = run_turn(
            agent,
            text,
            confirm_fn=lambda reply, diff: _cli_confirm(reply, diff, agent),
            on_event=emit,
        )
    finally:
        if finish:
            finish()
    if not emit:
        _render_turn(result.reply, result)
        return
    if result.diff:
        _render_diff(result.diff)
    _render_outcome(result)


def _cli_confirm(reply: str, diff: str, agent: Any = None) -> bool:  # noqa: ANN001 — PackageAgent
    """确认交互：回复已在流式直播中输出，这里展示 diff + 预计落点并询问。"""
    if diff:
        _render_diff(diff)
    landing = _landing_hint(agent) if agent is not None else None
    if landing:
        rprint(f"[green]确认后场景包将保存到 → {landing}[/green]")
    return select("确认变更", ["全部应用", "放弃"]) == "全部应用"


def _landing_hint(agent: Any) -> Path | None:  # noqa: ANN001 — PackageAgent
    """确认时刻的预计落点：暂存清单 id 已定则显示 ./<id>-package/（形态 B 归位预告）。

    归位预告随确认提示出现——草稿区路径只是会话中间态，确认前让用户看清最终落点。
    """
    import re as _re

    from agent_eval.packages import MANIFEST_FILENAME

    root = Path(getattr(agent.server, "root", ""))
    pid = agent.server.staged_manifest_id()
    if pid:
        slug = _re.sub(r"[^A-Za-z0-9._-]+", "-", pid).strip("-.") or "scenario"
        if root.name.startswith("agent-eval-pkg-"):  # 草稿区 → 会话后归位 cwd
            return Path.cwd() / f"{slug}-package"
        return root if root.name == f"{slug}-package" else Path.cwd() / f"{slug}-package"
    if not (root / MANIFEST_FILENAME).is_file():
        return None
    return root


def _session(agent: Any, first_text: str | None) -> None:
    """REPL 主循环：空输入退出；每轮 流式生成 → 确认 → 门禁 → 落盘/回滚。"""

    def _attempt(text: str) -> None:
        # 首轮与后续轮同防护：瞬时错误（如 LLM 网关断流）不杀会话，可见可重试
        try:
            _run_one(agent, text)
        except KeyboardInterrupt:
            rprint("\n[yellow]⏹ 已中断本轮（磁盘未受影响），可继续输入[/yellow]")
        except Exception as e:  # noqa: BLE001 — 会话内错误可见可继续下一轮
            rprint(f"[red]❌ 本轮失败: {e}[/red]")
            rprint("[dim]暂存与上下文已回滚，可直接重新输入上一条需求重试[/dim]")

    rprint(f"[dim]会话日志: {agent.log_path}（输入空行退出；Ctrl+C 中断当前轮）[/dim]")
    resumed = getattr(agent, "resumed_dialogue_count", 0)
    if resumed:
        rprint(f"[dim]已续接此前会话记录（{resumed} 条对话），Agent 可延续此前的讨论上下文[/dim]")
    if first_text:
        _attempt(first_text)
    while True:
        try:
            text = ask("你>")
        except typer.Abort:
            rprint("\n👋 会话结束")
            return
        if not text.strip():
            rprint("👋 会话结束")
            return
        _attempt(text)


def _guard_llm_ready() -> None:
    """LLM/deepagents 就绪检查：失败给出可操作指引（NF-C-03 降级）。"""
    from agent_eval.core.exceptions import AgentError

    try:
        from agent_eval.agent.model_bridge import build_chat_model

        build_chat_model("agent")
    except AgentError as e:
        rprint(f"[red]❌ Agent 不可用: {e}[/red]")
        rprint("[dim]配置: agent-eval models set；依赖: uv sync --extra agent[/dim]")
        raise typer.Exit(code=1) from e


def _run_noninteractive(agent: Any, text: str) -> None:  # noqa: ANN001 — PackageAgent
    """--yes --trust-agent 单轮执行（流式进度 + 自动确认；未落盘退出码 1）。"""
    from agent_eval.agent.package_agent import run_turn

    emit, finish = _stream_pair() or (None, None)
    if emit:
        rprint("[dim]⏳ Agent 执行中（--yes 自动确认，Ctrl+C 中断）…[/dim]")
    try:
        result = run_turn(agent, text, confirm_fn=lambda reply, diff: True, on_event=emit)
    finally:
        if finish:
            finish()
    if not emit:
        _render_turn(result.reply, result)
    elif result.diff:
        _render_diff(result.diff)
    if not result.committed:
        raise typer.Exit(code=1)


def _make_ask_fn() -> Any:
    """ask_user 桥（arch/15 §6.6）：SUT 探测工具的提问转发 CLI 交互原语。

    凭证录入走隐藏回显；返回值交探测工具内部处理（凭证直写密钥区，不回流对话）。
    长问题先独立展示再输入——塞进 ask/select 提示行会挤压成一行（实测不可读）。
    非交互（``--yes`` CI）形态不装配——工具面收到 ask_fn=None 自行返回「需交互」。
    """

    def _show(question: str) -> None:
        rprint(f"[bold]? {question}[/bold]")

    async def ask_fn(question: str, *, options: list[str] | None, secret: bool) -> str:
        if secret:
            _show(question)
            return ask("└─ 输入（隐藏回显）", hide=True)
        if options:
            _show(question)
            return select("└─ 选择", options)
        if len(question) <= 60:
            return ask(f"? {question}")
        _show(question)
        return ask("└─ 输入")

    return ask_fn


def _require_empty_dir(root: Path) -> None:
    if root.exists() and any(root.iterdir()):
        rprint(f"[red]❌ 目标目录非空: {root}（Agent 模式不覆盖，请换 --output）[/red]")
        raise typer.Exit(code=1)


def _default_packages_root() -> Path:
    """Agent 生成包的默认落盘根：**cwd 直出**（形态 B，2026-09 起取代 workspace 深埋）。

    场景包是源资产（考卷/规则/SUT 配置，用户要编辑、可团队共享），
    住进 ``workspace/``（运行产物区，gitignore）会造成资产进忽略区；
    行业脚手架惯例（cargo/npm/create-vite）一律 cwd 直出 ``<id>-package/``。
    不想进库的实验包由仓库 .gitignore 一行 ``/*-package/`` 表态。
    """
    return Path.cwd()


def _new_draft_root() -> Path:
    """新建草稿目录：``workspace/.staging/agent-eval-pkg-<rand>/``。

    会话中 Agent 在草稿里生成，结束后按清单 id 归位 cwd（同卷 move 原子）；
    草稿落在 workspace（gitignore 区），中断不清理——续作用 ``--output`` 指回。
    """
    import uuid

    from agent_eval.config.paths import paths

    return paths.default_workspace / ".staging" / f"agent-eval-pkg-{uuid.uuid4().hex[:8]}"


def _finalize_new_package(root: Path, movable: bool) -> Path:
    """Agent 拟定引用且未指定 --output：会话结束后按**最终清单 id** 归位。

    归位到 ``cwd/<id>-package/``（与 skeleton 模式 ``./<id>/`` 方向一致）；会话中
    自然语言改过包名也生效（迁移读的是最后一次落盘的清单）。
    """
    import re
    import shutil

    from agent_eval.packages import MANIFEST_FILENAME, load_manifest

    if not movable:
        return root
    if not (root / MANIFEST_FILENAME).is_file():
        rprint("[red]❌ 未能生成场景包（清单未落盘）[/red]")
        rprint(f"[yellow]草稿已保留（可续作）: {root}[/yellow]")
        raise typer.Exit(code=1)
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", load_manifest(root).id).strip("-.") or "scenario"
    final = Path.cwd() / f"{slug}-package"
    if final == root:
        _print_landed(final)
        return final
    if final.exists():
        rprint(f"[red]❌ 归位目标已存在: {final}[/red]")
        rprint(f"[yellow]包已生成、保留在草稿位: {root}[/yellow]")
        rprint(f"[dim]处理：换名重试，或手动 mv {root} {final}[/dim]")
        raise typer.Exit(code=1)
    final.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(root), str(final))
    _print_landed(final)
    return final


def _print_landed(final: Path) -> None:
    """归位成功提示：位置醒目 + gitignore 建议 + 后续命令。"""
    rprint(f"[green]✅ 场景包已保存 → {final}[/green]")
    rprint("[dim]后续: agent-eval scenario list / pipeline --package " + str(final) + "[/dim]")
    rprint("[dim]不想让实验包进 git？仓库 .gitignore 加一行: /*-package/[/dim]")


def agent_new_package(
    *,
    ref: str | None,
    output: Path | None,
    instruction: str | None,
    yes: bool,
    trust_agent: bool,
) -> Path:
    """``scenario new --mode agent``：自然语言生成完整场景包（REPL 会话）。

    ref 缺省时不问包名——Agent 在 workspace/.staging 草稿区生成，会话结束后按
    最终清单 id 归位 ``cwd/<id>-package/``（会话中自然语言改包名也生效）；
    给了 ref 默认落 ``cwd/<id>-package/``，给了 --output 则原地生成（支持指回
    草稿续作，非空目录放行）。
    """
    from agent_eval.agent.package_agent import PackageAgent
    from agent_eval.packages import parse_ref

    _guard_llm_ready()
    movable = ref is None and output is None  # 目录名后定 → 会话后归位
    if ref:
        scenario, package_id, _ = parse_ref(ref)
        package_id = package_id or scenario
        pin = f"{scenario}/{package_id}（以此为准，不得自拟其它 ID）"
        root = Path(output) if output else _default_packages_root() / f"{package_id}-package"
    else:
        pin = None
        root = (
            Path(output)
            if output
            else _new_draft_root()  # 草稿区（workspace/.staging），会话后归位 cwd
        )
    if output is None:
        # 默认路径要求空目录（不覆盖既有包）；--output 显式指定视为定址/续作，放行非空
        _require_empty_dir(root)
    root.mkdir(parents=True, exist_ok=True)
    if movable:
        rprint("[dim]包完成后将归位到 ./<包名>-package/（包名以 Agent 拟定的清单 id 为准）[/dim]")

    if not instruction:
        if yes and trust_agent:
            rprint("[red]❌ --yes --trust-agent 需配合 --instruction[/red]")
            raise typer.Exit(code=2)
        instruction = ask("描述评测需求（包名可由 Agent 拟定，会话中可自然语言修改）")

    agent = PackageAgent(root, ask_fn=None if (yes and trust_agent) else _make_ask_fn())
    first_text = PackageAgent.first_turn_text(instruction, new_package=True, ref=pin)
    try:
        if yes and trust_agent:
            _run_noninteractive(agent, first_text)
        else:
            _session(agent, first_text)
    except BaseException:
        # 中断 ≠ 放弃：草稿保留在 workspace/.staging（无论是否已落清单），续作用 --output 指回
        if movable:
            rprint(f"[yellow]⚠ 会话中断，草稿已保留: {root}[/yellow]")
            rprint(f"[dim]续作: agent-eval scenario new --mode agent --output {root}[/dim]")
        raise
    return _finalize_new_package(root, movable)


def agent_edit_package(
    *,
    ref: str,
    instruction: str | None,
    yes: bool,
    trust_agent: bool,
) -> None:
    """``scenario edit``：对项目包做自然语言增删改查（REPL 会话）。"""
    from agent_eval.agent.package_agent import PackageAgent
    from agent_eval.packages import MANIFEST_FILENAME, PackageManager

    _guard_llm_ready()
    path = Path(ref)
    if (path / MANIFEST_FILENAME).is_file():
        root = path
    else:
        try:
            pkg = PackageManager().resolve_ref(ref)
        except Exception as e:  # noqa: BLE001
            rprint(f"[red]❌ 无法解析场景包 {ref}: {e}[/red]")
            raise typer.Exit(code=1) from e
        if pkg.source == "builtin":
            rprint(
                f"[red]❌ 内置包只读: {pkg.manifest.ref}[/red]\n"
                f"[dim]如需改造：agent-eval scenario new <新包引用> --mode agent "
                f'--instruction "参照 {pkg.manifest.ref} 定制…"[/dim]'
            )
            raise typer.Exit(code=1)
        root = pkg.root

    interactive = not (instruction and yes and trust_agent)
    agent = PackageAgent(root, ask_fn=_make_ask_fn() if interactive else None)
    rprint(
        f"[bold]📦 Agent 改包会话[/bold] "
        f"[dim]{root}（沙盒：仅限包内；写操作经确认 + 校验后落盘）[/dim]"
    )
    if instruction and yes and trust_agent:
        _run_noninteractive(agent, instruction)
        return
    if yes or trust_agent:
        rprint("[red]❌ 非交互 Agent 需同时给 --yes 与 --trust-agent（默认关闭）[/red]")
        raise typer.Exit(code=2)
    _session(agent, instruction)
