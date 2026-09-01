"""agent-eval secrets — SUT 凭证管理（arch/06 §4.7 本机密钥区）。

通用 KV 录入（<ref>.<field>，字段名自由、隐藏输入），保存到
`~/.agent_eval/sut_credentials.json`（0600）。值不打印、不入日志。
"""

from __future__ import annotations

import os
from typing import Any

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
    if not _render_secrets():
        rprint(
            "[yellow]运行 [/yellow][bold]agent-eval secrets set <ref>.<field>[/bold][yellow] 录入。[/yellow]"
        )
        raise typer.Exit(code=1)


def _render_secrets() -> bool:
    """渲染已录凭证表（命令与工作台向导共用）；空返回 False。"""
    from agent_eval.execution.auth.secrets_store import load_secrets_file, secrets_file_path

    secrets = load_secrets_file()
    if not secrets:
        rprint(f"[yellow]未录入任何凭证（{secrets_file_path()} 不存在或为空）。[/yellow]")
        return False
    table = Table(title="SUT 凭证")
    table.add_column("ref", style="bold")
    table.add_column("field")
    for ref in sorted(secrets):
        for field in sorted(secrets[ref]):
            table.add_row(ref, field)
    rprint(table)
    rprint(f"[dim]存储于 {secrets_file_path()}（0600，值不回显）[/dim]")
    return True


def _discover_credential_refs() -> list[str]:
    """从场景包 sut_configs 收集 ``auth.credential_ref``（数据驱动发现，非代码枚举）。"""
    import yaml

    from agent_eval.packages import PackageManager

    refs: set[str] = set()
    try:
        pkgs = PackageManager().list()
    except Exception:  # noqa: BLE001 — 发现失败不影响录入（可手输 ref）
        return []
    for pkg in pkgs:
        cfg_dir = pkg.root / "sut_configs"
        if not cfg_dir.is_dir():
            continue
        for cfg in cfg_dir.glob("*.yaml"):
            try:
                data = yaml.safe_load(cfg.read_text(encoding="utf-8")) or {}
            except Exception:  # noqa: BLE001 — 坏配置跳过
                continue
            ref = ((data.get("sut") or data).get("auth") or {}).get("credential_ref")
            if ref:
                refs.add(str(ref))
    return sorted(refs)


def secrets_wizard() -> None:
    """工作台「SUT 凭证」交互子向导：查看 / 录入 / 删除（纯函数动作，workbench 复用）。

    凭证是**通用 KV**（06 §4.7，``<ref>.<field>`` 字段名自由、不绑定凭证形态）：
    录入时字段名自由输入（sut_config 的 body_template 引用什么就录什么），
    ref 沿已录键与场景包 sut_configs 的 credential_ref 数据发现供选，不枚举固定集。
    """
    from agent_eval.cli.console.prompts import ask, confirm, select
    from agent_eval.execution.auth.secrets_store import load_secrets_file, save_secrets_file

    rprint("[dim]凭证 = <ref>.<field> 通用 KV（字段名自由）；值隐藏输入，存储 0600。[/dim]")
    while True:
        action = select("SUT 凭证", ["查看已录凭证", "录入 / 更新凭证", "删除凭证", "返回"])
        if action == "返回":
            return
        if action == "查看已录凭证":
            if not _render_secrets():
                rprint(
                    "[dim]→ 选「录入 / 更新凭证」，或命令行 agent-eval secrets set <ref>.<field>[/dim]"
                )
            continue
        if action == "录入 / 更新凭证":
            existing = sorted(load_secrets_file())
            discovered = [r for r in _discover_credential_refs() if r not in existing]
            options = (
                [f"{r}（已录，更新）" for r in existing]
                + [f"{r}（场景包引用）" for r in discovered]
                + ["➕ 新增 ref…"]
            )
            ref = (
                select("选择 ref（credential_ref）", options).split("（")[0].strip()
                if len(options) > 1
                else ask("ref（sut_config 的 credential_ref，如 SASAN）")
            )
            if ref.startswith("➕"):
                ref = ask("新 ref（自由命名，如 SASAN / AGENT_SERVER）")
            if not ref:
                rprint("[yellow]未输入 ref，已取消。[/yellow]")
                continue
            field = ask(
                f"{ref} 的字段名（自由命名——sut_config 模板引用什么就录什么，如 username/api_key）"
            )
            if not field:
                rprint("[yellow]未输入字段名，已取消。[/yellow]")
                continue
            value = ask(f"{ref}.{field} 的值", hide=True)
            if not value:
                rprint("[yellow]未输入值，已取消。[/yellow]")
                continue
            secrets = load_secrets_file()
            secrets.setdefault(ref, {})[field] = value
            path = save_secrets_file(secrets)
            rprint(f"[green]✅ 已保存[/green] {ref}.{field} → {path}（0600）")
            continue
        # 删除凭证
        secrets = load_secrets_file()
        keys = [f"{r}.{f}" for r in sorted(secrets) for f in sorted(secrets[r])]
        if not keys:
            rprint("[yellow]未录入任何凭证。[/yellow]")
            continue
        key = select("选择要删除的凭证", [*keys, "取消"])
        if key == "取消" or not confirm(f"确认删除 {key}"):
            continue
        ref, field = key.split(".", 1)
        secrets[ref].pop(field)
        if not secrets[ref]:
            secrets.pop(ref)
        save_secrets_file(secrets)
        rprint(f"[green]✅ 已删除[/green] {key}")


# ── 执行前凭证保障（req/04 §3.5：按所选 SUT 的 credential_ref 引导补齐缺失字段）──


def ensure_sut_credentials(sut: Any) -> None:
    """执行前凭证保障（execute_stage 调用）：缺失时交互补录，复检仍缺则 fail fast。

    交互终端：列出缺失字段 → 确认后逐项隐藏输入 → **一次落盘**（不留半截
    状态）→ 复检通过即继续执行；用户取消 / 空输入则退回预检原样抛
    SUTAuthError（带 ``secrets set`` 引导）。``--no-input``（CI / 管道）不
    交互，行为与原先完全一致。字段集由 sut_config 数据推导（06 §4.7 通用 KV）。
    """
    from agent_eval.execution.auth.credentials import (
        missing_credential_fields,
        preflight_sut_credentials,
    )

    missing = missing_credential_fields(sut)
    if missing and not os.environ.get("AGENT_EVAL_NO_INPUT"):
        _fill_missing_credentials(sut, missing)  # 取消/失败不在此抛，交由复检
    preflight_sut_credentials(sut)  # 复检：仍缺（含 ref 缺失等配置错误）即原样 fail fast


def _fill_missing_credentials(sut: Any, missing: list[str]) -> None:
    """交互补录 sut 缺失凭证字段（隐藏输入，一次落盘；任一空输入整体取消）。"""
    from agent_eval.cli.console.prompts import ask, confirm
    from agent_eval.execution.auth.secrets_store import load_secrets_file, save_secrets_file

    ref = str(getattr(getattr(sut, "auth", None), "credential_ref", ""))
    keys = ", ".join(f"{ref}.{field}" for field in missing)
    rprint(f"[yellow]⚠ SUT {sut.name} 缺少凭证: {keys}（sut_config 声明）[/yellow]")
    if not confirm("现在录入？（隐藏输入，保存到本机密钥区 0600）", default=True):
        return
    values: dict[str, str] = {}
    for field in missing:
        value = ask(f"{ref}.{field}", hide=True)
        if not value:
            rprint(f"[yellow]未输入 {ref}.{field}，已取消补录。[/yellow]")
            return
        values[field] = value
    secrets = load_secrets_file()
    secrets.setdefault(ref, {}).update(values)
    path = save_secrets_file(secrets)
    rprint(f"[green]✅ 已保存[/green] {keys} → {path}（0600）")


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
