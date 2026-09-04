"""场景包 Agent 会话入口 — REPL 式自然语言改包（arch/15 §六，requirement F-C-SCN-AGENT）。

用户在 CLI 持续输入自然语言（``你> ...``），WorkbenchAgent 经沙盒工具面改包，工作
过程**流式直播**（claude code 式：回复 token 直出 + 工具调用行实时可见）；每轮展示
diff → 确认（全部应用/放弃）→ 校验门禁 → 原子落盘。空行退出会话；Ctrl+C 暂停当前轮
（进度保留，输入「继续」接着跑、「放弃」回滚暂存——§6.7 D-WB-4）。
非交互形态（CI）需 ``--instruction`` + ``--yes --trust-agent`` 双开关。
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import typer
from rich import print as rprint

from agent_eval.cli.console.agent_stream import make_stream_emitter
from agent_eval.cli.console.prompts import ask, select

__all__ = ["agent_edit_package", "agent_new_package"]

_DIFF_MAX_LINES = 80  # diff 终端预览截断（完整内容落盘为准，超长节略展示）
_ASK_INLINE_QUESTION_CHARS = 60  # ask 桥单行提示的问题长度上限（超长改两行式展示）


def _render_diff(diff: str) -> None:
    rprint("[dim]── diff（暂存 vs 磁盘）──[/dim]")
    for line in diff.splitlines()[:_DIFF_MAX_LINES]:
        color = "green" if line.startswith("+") else ("red" if line.startswith("-") else "")
        rprint(f"[{color}]{line}[/{color}]" if color else line)


def _render_outcome(result: Any, landing: Path | None = None) -> None:  # noqa: ANN001 — TurnResult
    if result.committed:
        rprint(f"[green]✅ 已落盘[/green]（{len(result.committed_files)} 个文件变更）")
        if landing is not None:
            # 归位发生在会话结束而非此刻——落盘时刻说清时序（实测：用户确认后在
            # 预告路径找不到包，以为落盘丢失）
            rprint(f"[dim]会话结束（输入空行退出）后归位 → {landing}[/dim]")
    elif result.aborted_reason == "user_aborted":
        rprint("[yellow]↩️ 已放弃本轮（磁盘未受影响）[/yellow]")
    elif result.aborted_reason == "segment_limit":
        rprint("[yellow]⏸ 已达自动分段上限，已暂停（进度完整保留在暂存与对话中）[/yellow]")
        rprint("[dim]说「继续」接着跑；或调高 --max-segments；输入「放弃」回滚暂存[/dim]")
    elif result.aborted_reason == "budget_exceeded":
        rprint("[yellow]⏸ 已达会话预算上限，已暂停（进度完整保留在暂存与对话中）[/yellow]")
        rprint("[dim]说「继续」接着跑；或调高 --budget-usd；输入「放弃」回滚暂存[/dim]")
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


def _stream_pair() -> tuple[Callable[[dict[str, Any]], None], Callable[[], None]] | None:
    """流式开关：JSON 模式下 stdout 仅 JSON（F-C-INTEG-02），返回 None 走静默路径。"""
    from agent_eval.cli.console.output import is_json

    return None if is_json() else make_stream_emitter()


def _run_one(agent: Any, text: str) -> None:  # noqa: ANN001 — WorkbenchAgent
    """执行并渲染一轮：流式直播（回复不重复打印）或非流式兜底。"""
    from agent_eval.agent.workbench_agent import run_turn

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
    if result.committed:
        # 确认环节已展示过 diff，不再重画（实测：确认后再出一份完整 diff 被误读为
        # 「还有一份未应用」）；已落盘时补归位时序提示
        _render_outcome(result, _landing_hint(agent))
        return
    _render_outcome(result)


def _cli_confirm(reply: str, diff: str, agent: Any = None) -> bool:  # noqa: ANN001 — WorkbenchAgent
    """确认交互：回复已在流式直播中输出，这里展示 diff + 预计落点并询问。"""
    if diff:
        _render_diff(diff)
    landing = _landing_hint(agent) if agent is not None else None
    if landing:
        rprint(f"[green]确认落盘后，会话结束（输入空行退出）即归位 → {landing}[/green]")
    return select("确认变更", ["全部应用", "放弃"]) == "全部应用"


def _landing_hint(agent: Any) -> Path | None:  # noqa: ANN001 — WorkbenchAgent
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
        return root  # 非草稿区（edit / --output 定址）原地生效，落点就是 root
    if not (root / MANIFEST_FILENAME).is_file():
        return None
    return root


def agent_workbench_entry(session: Any = None) -> None:  # noqa: ANN001 — WorkbenchSession
    """``start`` 主菜单一级入口（§3.5）：横幅介绍能力后**直入对话**（Claude Code 式）。

    无前置菜单——新建 / 改已有包 / 排查都是会话里的一句话（能力与样例见横幅，
    §6.10）。默认任务对象为新包草稿（workspace/.staging，会话后按清单 id 归位
    ``cwd/<id>-package/``）；改已有项目包由 Agent 经 read_file 读入现有内容后在
    草稿中改造（prompts 域段规约）。LLM 未配置在此阻断（无模型 Agent 不可用）。
    """
    from agent_eval.agent.workbench_agent import WorkbenchAgent
    from agent_eval.packages import MANIFEST_FILENAME

    _guard_llm_ready()
    root = _new_draft_root()
    root.mkdir(parents=True)
    rprint("[dim]包完成后将归位到 ./<包名>-package/（包名以 Agent 拟定的清单 id 为准）[/dim]")
    agent = WorkbenchAgent(root, ask_fn=_make_ask_fn())
    _render_intro(agent)
    try:
        _session(agent, None, show_intro=False)
    except BaseException:
        # 中断 ≠ 放弃：半途草稿保留（与 agent_new_package 同约定）；清单已落盘 =
        # 成果已完整，照常归位不困在草稿区
        if (root / MANIFEST_FILENAME).is_file():
            _finalize_new_package(root, movable=True)
            return
        rprint(f"[yellow]⚠ 会话中断，草稿已保留: {root}[/yellow]")
        rprint(f"[dim]续作: agent-eval scenario new --mode agent --output {root}[/dim]")
        raise
    if not any(root.iterdir()):
        root.rmdir()  # 空会话（用户看一眼就退出）不留草稿残目录
        return
    _finalize_new_package(root, movable=True)


def _render_intro(agent: Any) -> None:  # noqa: ANN001 — WorkbenchAgent
    """启动自我介绍横幅（§6.10）：资产文案 rich Panel 渲染；--json 与非 TTY 静默。"""
    from rich.panel import Panel
    from rich.text import Text

    from agent_eval.cli.console.output import is_json

    if is_json() or not sys.stdout.isatty():
        return
    text = agent.intro_text()
    if not text:
        return
    # 定宽上限：超宽终端不拉满整行（CJK 双宽下超宽 Panel 易被终端渲染截断）
    from rich.console import Console

    width = min(Console().width or 100, 100)
    rprint(Panel(Text(text.rstrip()), border_style="cyan", title="工作台 Agent", width=width))


def _session(agent: Any, first_text: str | None, *, show_intro: bool = True) -> None:
    """REPL 主循环：空输入退出；每轮 流式生成 → 确认 → 门禁 → 落盘/回滚。

    启动渲染自我介绍横幅（§6.10，会话日志行之前）；入口已渲染过横幅时以
    ``show_intro=False`` 抑制，避免重复（§3.5 直入对话形态）。
    中断/瞬时错误 = 暂停保现场（§6.7 D-WB-4）：暂存与对话上下文完整，「继续」
    接着跑；「放弃」是唯一回滚触发器（显式指令，防误触丢进度）。
    """
    import asyncio

    if show_intro:
        _render_intro(agent)

    def _attempt(text: str) -> None:
        try:
            _run_one(agent, text)
        except (KeyboardInterrupt, asyncio.CancelledError):
            rprint("\n[yellow]⏸ 已暂停（进度已保留：暂存草稿与对话上下文完整）[/yellow]")
            rprint("[dim]输入「继续」接着跑，或直接说下一步；输入「放弃」回滚本轮暂存改动[/dim]")
        except Exception as e:  # noqa: BLE001 — 会话内错误可见可继续下一轮
            rprint(f"[red]❌ 本轮失败: {e}[/red]")
            rprint("[dim]进度已保留——可直接重试；输入「放弃」回滚本轮暂存改动[/dim]")

    def _maybe_abandon(text: str) -> bool:
        if text.strip() not in ("放弃", "abort"):
            return False
        if not agent.server.has_staged_changes:
            rprint("[dim]当前没有待确认的暂存改动[/dim]")
            return True
        agent.abandon_pending()
        rprint("[yellow]↩️ 已放弃暂存改动（磁盘未受影响，对话上下文保留）[/yellow]")
        return True

    rprint(f"[dim]会话日志: {agent.log_path}（输入空行退出；Ctrl+C 暂停当前轮）[/dim]")
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
        if _maybe_abandon(text):
            continue
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


def _run_noninteractive(agent: Any, text: str) -> None:  # noqa: ANN001 — WorkbenchAgent
    """--yes --trust-agent 单轮执行（流式进度 + 自动确认；未落盘退出码 1）。"""
    from agent_eval.agent.workbench_agent import run_turn

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
    if result.aborted_reason in ("segment_limit", "budget_exceeded"):
        _render_outcome(result)
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
        if len(question) <= _ASK_INLINE_QUESTION_CHARS:
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
    max_turns: int = 40,
    max_segments: int = 3,
    budget_usd: float | None = None,
) -> Path:
    """``scenario new --mode agent``：自然语言生成完整场景包（REPL 会话）。

    ref 缺省时不问包名——Agent 在 workspace/.staging 草稿区生成，会话结束后按
    最终清单 id 归位 ``cwd/<id>-package/``（会话中自然语言改包名也生效）；
    给了 ref 默认落 ``cwd/<id>-package/``，给了 --output 则原地生成（支持指回
    草稿续作，非空目录放行）。
    """
    from agent_eval.agent.workbench_agent import WorkbenchAgent, WorkbenchAgentConfig
    from agent_eval.packages import MANIFEST_FILENAME, parse_ref

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

    agent = WorkbenchAgent(
        root,
        config=WorkbenchAgentConfig(
            max_turns=max_turns, max_segments=max_segments, budget_usd=budget_usd
        ),
        ask_fn=None if (yes and trust_agent) else _make_ask_fn(),
    )
    first_text = WorkbenchAgent.first_turn_text(instruction, new_package=True, ref=pin)
    try:
        if yes and trust_agent:
            _run_noninteractive(agent, first_text)
        else:
            _session(agent, first_text)
    except BaseException:
        # 中断 ≠ 放弃：半途草稿保留在 workspace/.staging（续作 --output 指回）。
        # 但清单已落盘 = 至少完成过一次确认落盘、成果已完整——中断只是结束对话，
        # 照常归位，不把完整包困在草稿区（实测：确认落盘后 Ctrl+C 退出会话，
        # 归位预告的路径下找不到包）
        if movable and (root / MANIFEST_FILENAME).is_file():
            return _finalize_new_package(root, movable)
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
    max_turns: int = 40,
    max_segments: int = 3,
    budget_usd: float | None = None,
) -> None:
    """``scenario edit``：对项目包做自然语言增删改查（REPL 会话）。"""
    from agent_eval.agent.workbench_agent import WorkbenchAgent, WorkbenchAgentConfig
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
    agent = WorkbenchAgent(
        root,
        config=WorkbenchAgentConfig(
            max_turns=max_turns, max_segments=max_segments, budget_usd=budget_usd
        ),
        ask_fn=_make_ask_fn() if interactive else None,
    )
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
