"""场景包 Agent 会话入口 — REPL 式自然语言改包（arch/15 §六，requirement F-C-SCN-AGENT）。

用户在 CLI 持续输入自然语言（``你> ...``），PackageAgent 经沙盒工具面改包，
每轮展示计划 + diff → 确认（全部应用/放弃）→ 校验门禁 → 原子落盘；
空输入退出会话。非交互形态（CI）需 ``--instruction`` + ``--yes --trust-agent`` 双开关。
"""

from __future__ import annotations

from pathlib import Path

import typer
from rich import print as rprint

from agent_eval.cli.console.prompts import ask, select

__all__ = ["agent_edit_package", "agent_new_package"]


def _render_diff(diff: str, max_lines: int = 80) -> None:
    rprint("[dim]── diff（暂存 vs 磁盘）──[/dim]")
    for line in diff.splitlines()[:max_lines]:
        color = "green" if line.startswith("+") else ("red" if line.startswith("-") else "")
        rprint(f"[{color}]{line}[/{color}]" if color else line)


def _render_turn(reply: str, result) -> None:  # noqa: ANN001 — TurnResult
    if reply:
        lines = reply.splitlines()
        rprint(f"[bold cyan]🤖 {lines[0]}[/bold cyan]")
        for line in lines[1:6]:
            rprint(f"   [dim]{line}[/dim]")
    if result.diff:
        _render_diff(result.diff)
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


def _cli_confirm(reply: str, diff: str) -> bool:
    if reply:
        rprint(f"[bold cyan]🤖 {reply.splitlines()[0]}[/bold cyan]")
    if diff:
        _render_diff(diff)
    return select("确认变更", ["全部应用", "放弃"]) == "全部应用"


def _session(agent, first_text: str | None) -> None:  # noqa: ANN001 — PackageAgent
    """REPL 主循环：空输入退出；每轮 确认 → 门禁 → 落盘/回滚。"""
    from agent_eval.agent.package_agent import run_turn

    rprint(f"[dim]会话日志: {agent.log_path}（输入空行退出）[/dim]")
    if first_text:
        _render_turn("", run_turn(agent, first_text, confirm_fn=_cli_confirm))
    while True:
        try:
            text = ask("你>")
        except typer.Abort:
            rprint("\n👋 会话结束")
            return
        if not text.strip():
            rprint("👋 会话结束")
            return
        try:
            result = run_turn(agent, text, confirm_fn=_cli_confirm)
        except Exception as e:  # noqa: BLE001 — 会话内错误可见可继续下一轮
            rprint(f"[red]❌ 本轮失败: {e}[/red]")
            continue
        _render_turn(result.reply, result)


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


def agent_new_package(
    *,
    ref: str,
    output: Path | None,
    instruction: str | None,
    yes: bool,
    trust_agent: bool,
) -> Path:
    """``scenario new --mode agent``：自然语言生成完整场景包（REPL 会话）。"""
    from agent_eval.agent.package_agent import PackageAgent, run_turn
    from agent_eval.packages import parse_ref

    _guard_llm_ready()
    scenario, package_id, _ = parse_ref(ref)
    package_id = package_id or scenario
    root = Path(output) if output else Path.cwd() / f"{package_id}-package"
    if root.exists() and any(root.iterdir()):
        rprint(f"[red]❌ 目标目录非空: {root}（Agent 模式不覆盖，请换 --output）[/red]")
        raise typer.Exit(code=1)
    root.mkdir(parents=True, exist_ok=True)

    if not instruction:
        if yes and trust_agent:
            rprint("[red]❌ --yes --trust-agent 需配合 --instruction[/red]")
            raise typer.Exit(code=2)
        instruction = ask("描述评测需求（生成完整场景包）")

    agent = PackageAgent(root)
    first_text = PackageAgent.first_turn_text(
        instruction, new_package=True, ref=f"{scenario}/{package_id}"
    )
    if yes and trust_agent:
        result = run_turn(agent, first_text, confirm_fn=lambda reply, diff: True)
        _render_turn(result.reply, result)
        if not result.committed:
            raise typer.Exit(code=1)
    else:
        _session(agent, first_text)
    return root


def agent_edit_package(
    *,
    ref: str,
    instruction: str | None,
    yes: bool,
    trust_agent: bool,
) -> None:
    """``scenario edit``：对项目包做自然语言增删改查（REPL 会话）。"""
    from agent_eval.agent.package_agent import PackageAgent, run_turn
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

    agent = PackageAgent(root)
    rprint(
        f"[bold]📦 Agent 改包会话[/bold] "
        f"[dim]{root}（沙盒：仅限包内；写操作经确认 + 校验后落盘）[/dim]"
    )
    if instruction and yes and trust_agent:
        result = run_turn(agent, instruction, confirm_fn=lambda reply, diff: True)
        _render_turn(result.reply, result)
        if not result.committed:
            raise typer.Exit(code=1)
        return
    if yes or trust_agent:
        rprint("[red]❌ 非交互 Agent 需同时给 --yes 与 --trust-agent（默认关闭）[/red]")
        raise typer.Exit(code=2)
    _session(agent, instruction)
