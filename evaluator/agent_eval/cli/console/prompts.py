"""向导原语 — select / confirm / ask 统一收口。

编号选择（gcloud 同款交互）。``--no-input``（``AGENT_EVAL_NO_INPUT``）下走旁路：
``env_key`` 或 ``default`` 提供则直接采用，否则报错退出（exit 2），**绝不挂起等待**
（F-C-INTEG-01）。普通管道输入（CliRunner 脚本化 / expect）不受影响，正常提示。
所有人机 IO 必须经过本模块（组织约定 5），业务与编排层零交互依赖。
"""

from __future__ import annotations

import os
import sys
from typing import NoReturn

import typer
from rich import print as rprint

__all__ = ["ask", "confirm", "resolve_bypass", "select"]


def _no_input() -> bool:
    """仅 --no-input 全局开关视为禁交互（非 TTY 但有管道输入时仍可提示）。"""
    return bool(os.environ.get("AGENT_EVAL_NO_INPUT"))


def _fail_missing_input(label: str, hint: str = "") -> NoReturn:
    rprint(f"[red]❌ --no-input 下缺少必需输入: {label}[/red]")
    if hint:
        rprint(f"[dim]{hint}[/dim]")
    rprint("[dim]旁路方式：经参数 / 环境变量提供，或交互终端运行。[/dim]")
    raise typer.Exit(code=2)


def _match_option(raw: str, options: list[str]) -> str | None:
    """按编号（1 起）或选项原文匹配；不匹配返回 None。"""
    raw = raw.strip()
    if raw.isdigit() and 1 <= int(raw) <= len(options):
        return options[int(raw) - 1]
    return raw if raw in options else None


def _default_index(default: int | str | None, options: list[str]) -> int:
    if default is None:
        return 1
    if isinstance(default, int):
        return default if 1 <= default <= len(options) else 1
    return options.index(default) + 1 if default in options else 1


def resolve_bypass(env_key: str, options: list[str]) -> str | None:
    """解析 env 旁路值：精确 / 编号 / 唯一前缀（空格或 ``/`` 分界）匹配选项。

    供「无参交互选择」helper 在进入向导前消费 env 旁路（选项常带展示后缀，
    如 ``chat/chat:1.0.0  (builtin)``，裸值 ``chat`` 需前缀匹配）；多义或不
    匹配报错退出（exit 2）。无 env 值返回 None，由调用方进入交互选择。
    """
    raw = os.environ.get(env_key, "").strip()
    if not raw:
        return None
    exact = _match_option(raw, options)
    if exact is not None:
        return exact
    hits = [o for o in options if o.startswith(raw + " ") or o.startswith(raw + "/")]
    if len(hits) == 1:
        return hits[0]
    if len(hits) > 1:
        rprint(f"[red]❌ {env_key}={raw} 匹配多个候选: {'; '.join(hits)}[/red]")
    else:
        rprint(f"[red]❌ {env_key}={raw} 不在可选项内[/red]")
    raise typer.Exit(code=2)


def select(
    label: str,
    options: list[str],
    *,
    default: int | str | None = None,
    env_key: str | None = None,
    no_default: bool = False,
) -> str:
    """单选：编号列表 + 回车确认；--no-input 下走 env/default 旁路。

    ``no_default=True``（放行类选择专用）：空回车不再隐式选第一项，
    提示改「输入编号」、空输入按无效选择重问。隐式默认曾是安全纵伤——host
    授权/凭证外发/执行确认/落盘确认的选择器空回车一律落放行项（「允许」
    「确认执行」「全部应用」），而编号列表从未展示默认态，「回车确认」的
    承诺无凭。
    """
    if not options:
        rprint(f"[red]❌ 无可选项: {label}[/red]")
        raise typer.Exit(code=2)

    bypass = os.environ.get(env_key, "").strip() if env_key else ""
    if bypass:
        matched = _match_option(bypass, options)
        if matched is None:
            rprint(f"[red]❌ {env_key}={bypass} 不在可选项内[/red]")
            raise typer.Exit(code=2)
        return matched

    if _no_input():
        if no_default:
            default = None  # 放行类无默认：--no-input 必须显式提供（ask_fn 场景不可达）
        if default is None:
            _fail_missing_input(
                label, hint=f"可设环境变量 {env_key or 'AGENT_EVAL_SELECT'} 提供选择"
            )
        matched = _match_option(str(default), options)
        if matched is None:
            _fail_missing_input(label, hint=f"default={default} 不在可选项内")
        return matched

    default_idx = _default_index(default, options)
    hint = "输入编号" if no_default else "输入编号，回车确认"
    rprint(f"[bold]? {label}[/bold] [dim][{hint}][/dim]")
    for i, opt in enumerate(options, 1):
        rprint(f"  [cyan]{i}.[/cyan] {opt}")
    while True:
        if no_default:
            # 空回车落 "" → 无效选择重问（click 对 default="" 直通空串，不内部重问）
            raw = str(typer.prompt("选择", default="", show_default=False))
        else:
            raw = str(typer.prompt("选择", default=str(default_idx), show_default=False))
        matched = _match_option(raw, options)
        if matched is not None:
            return matched
        rprint(f"[red]无效选择，请输入 1-{len(options)}[/red]")


def confirm(label: str, *, default: bool = False, env_key: str | None = None) -> bool:
    """确认（y/n）；--no-input 下走 env/default 旁路。"""
    if env_key:
        value = os.environ.get(env_key)
        if value is not None and value.strip():
            return value.strip().lower() in ("1", "true", "yes", "y")
    if _no_input():
        return default
    return bool(typer.confirm(f"? {label}", default=default))


def _maskable() -> bool:
    """掩码回显前提：交互 TTY 且 termios 可用；缺一则回退 click 隐藏回显。

    管道 / CliRunner / 非 POSIX（Windows，无 termios）下不启用——脚本化输入
    行为与既有测试完全不变。
    """
    try:
        import termios  # noqa: F401 — 仅探测可用性（Windows 无此模块）
    except ImportError:
        return False
    return sys.stdin is not None and sys.stdin.isatty()


def _masked_input(prompt: str) -> str:
    """掩码回显输入（POSIX termios cbreak）：逐键 ``*`` 上屏、退格抹除。

    click 的 hide_input 全静默，用户无法感知输入是否生效。
    cbreak 保留 ISIG——^C 仍以 KeyboardInterrupt 中断；
    ^D / 读尽视为 EOF 抛 Abort（与 click.prompt 同语义，ask_fn 桥已有
    Abort→KI 转换）。终端态 finally 复原，中断路径不残留原始回显。
    """
    import termios
    import tty

    typer.echo(prompt, nl=False)
    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)
    chars: list[str] = []
    try:
        tty.setcbreak(fd)
        while True:
            ch = sys.stdin.read(1)
            if ch in ("\r", "\n"):
                typer.echo()
                return "".join(chars)
            if ch in ("\x7f", "\b"):
                if chars:
                    chars.pop()
                    typer.echo("\b \b", nl=False)
                continue
            if ch in ("", "\x04"):  # ^D / 流尽 = EOF，与 click.prompt 的 Abort 同语义
                typer.echo()
                raise typer.Abort()
            chars.append(ch)
            typer.echo("*", nl=False)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)


def ask(
    label: str,
    *,
    default: str | None = None,
    env_key: str | None = None,
    hide: bool = False,
) -> str:
    """文本输入；``hide=True`` 敏感输入掩码回显（逐键 ``*`` 上屏可感知）。

    --no-input 下走 env/default 旁路。掩码仅在交互 TTY + POSIX（termios
    可用）启用；管道 / CliRunner / 非 POSIX 退回 click 隐藏回显（行为不变）。
    """
    if env_key:
        value = os.environ.get(env_key)
        if value is not None and value.strip():
            return value.strip()
    if _no_input():
        if default is None:
            _fail_missing_input(
                label, hint=f"可设环境变量 {env_key or 'AGENT_EVAL_INPUT'} 提供取值"
            )
        return default
    if hide and _maskable():
        value = _masked_input(f"? {label}: ")
    else:
        value = str(
            typer.prompt(
                f"? {label}",
                default=default if default is not None else "",
                hide_input=hide,
                show_default=bool(default),
            )
        )
    value = value.strip()
    return value or (default or "")
