"""agent-eval secrets — SUT 凭证管理（arch/06 §4.7 本机密钥区）。

通用 KV 录入（<ref>.<field>，字段名自由、隐藏输入），保存到
`~/.agent_eval/sut_credentials.json`（0600）。值不打印、不入日志。
"""

from __future__ import annotations

import typer
from rich import print as rprint
from rich.table import Table

secrets_app = typer.Typer(help="SUT 凭证管理（set / list / delete）")


def _parse_key(key: str) -> tuple[str, str]:
    """解析 `<ref>.<field>`；非法时退出并提示。"""
    ref, _, field = key.partition(".")
    if not ref or not field:
        rprint(f"[red]键格式应为 <ref>.<field>（如 sasan.username），得到: {key!r}[/red]")
        raise typer.Exit(code=1)
    return ref, field


@secrets_app.command("set")
def set_secret(key: str) -> None:
    """录入凭证字段（隐藏输入），保存到 ~/.agent_eval/sut_credentials.json（0600）。"""
    from agent_eval.execution.auth.secrets_store import (
        load_secrets_file,
        save_secrets_file,
    )

    ref, field = _parse_key(key)
    value = typer.prompt("值", hide_input=True, default="").strip()
    if not value:
        rprint("[red]未输入值，已取消。[/red]")
        raise typer.Exit(code=1)

    secrets = load_secrets_file()
    secrets.setdefault(ref, {})[field] = value
    path = save_secrets_file(secrets)
    rprint(f"[green]✅ 已保存[/green] {key} → {path}（0600）")


@secrets_app.command("list")
def list_secrets() -> None:
    """查看已录凭证键清单（不显示值）。"""
    from agent_eval.execution.auth.secrets_store import load_secrets_file, secrets_file_path

    secrets = load_secrets_file()
    if not secrets:
        rprint(f"[yellow]未录入任何凭证（{secrets_file_path()} 不存在或为空）。[/yellow]")
        rprint(
            "[yellow]运行 [/yellow][bold]agent-eval secrets set <ref>.<field>[/bold][yellow] 录入。[/yellow]"
        )
        raise typer.Exit(code=1)

    table = Table(title="SUT 凭证")
    table.add_column("ref", style="bold")
    table.add_column("field")
    for ref in sorted(secrets):
        for field in sorted(secrets[ref]):
            table.add_row(ref, field)
    rprint(table)
    rprint(f"[dim]存储于 {secrets_file_path()}（0600，值不回显）[/dim]")


@secrets_app.command("delete")
def delete_secret(
    key: str, force: bool = typer.Option(False, "--force", "-f", help="跳过确认")
) -> None:
    """删除指定凭证字段。"""
    from agent_eval.execution.auth.secrets_store import load_secrets_file, save_secrets_file

    ref, field = _parse_key(key)
    secrets = load_secrets_file()
    if field not in secrets.get(ref, {}):
        rprint(f"[yellow]未录入该键: {key}[/yellow]")
        raise typer.Exit(code=1)
    if not force and not typer.confirm(f"确认删除 {key}"):
        rprint("已取消。")
        return

    secrets[ref].pop(field)
    if not secrets[ref]:
        secrets.pop(ref)
    save_secrets_file(secrets)
    rprint(f"[green]✅ 已删除[/green] {key}")
