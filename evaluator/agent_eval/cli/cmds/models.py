"""agent-eval models — LLM 配置管理（交互式向导，arch/06 §4.6 CLI 形态）。

向导式选择提供商与模型、隐藏输入 api-key，保存到 ``~/.agent_eval/llm.json``（0600）。
密钥不打印、不入日志。Sprint 10 命令重命名：``login/logout`` → ``set/clear``
（「login」语义保留给平台账号 auth，requirement/04 §3.3）。
"""

from __future__ import annotations

import time

import typer
from rich import print as rprint
from rich.table import Table

models_app = typer.Typer(help="LLM 模型配置管理（set / list / test / clear）")

_PROVIDER_OPTIONS = ["anthropic", "openai", "deepseek", "custom（自定义 OpenAI 兼容）"]


def _mask(secret: str) -> str:
    return f"{secret[:4]}…{secret[-4:]}" if len(secret) > 8 else "****"


@models_app.command("set")
def models_set() -> None:
    """交互式配置模型（提供商/模型/api-key），保存到 ~/.agent_eval/llm.json（0600）。"""
    from agent_eval.cli.console.prompts import select
    from agent_eval.config.llm_file import (
        PROVIDER_DEFAULT_BASE_URLS,
        ROLE_MODEL_SUGGESTIONS,
        LLMFileConfig,
        RoleConfig,
        llm_file_path,
        load_llm_file,
        save_llm_file,
    )

    existing = load_llm_file() or LLMFileConfig()
    rprint("[bold]═ LLM 配置向导 ═[/bold]（保存到 " + str(llm_file_path()) + "，权限 0600）")

    choice = select("选择提供商", _PROVIDER_OPTIONS)
    proto = "openai" if choice.startswith("custom") else choice
    current_text = existing.roles.get("text")
    default_base = PROVIDER_DEFAULT_BASE_URLS.get(proto) or (
        current_text.base_url if current_text else None
    )
    base_url = typer.prompt("API Base URL", default=default_base or "")
    api_key = typer.prompt("API Key（隐藏输入）", hide_input=True, default="").strip()
    if not api_key:
        rprint("[red]未输入 API Key，已取消。[/red]")
        raise typer.Exit(code=1)

    def ask_model(role: str) -> str | None:
        # text 为建议必配角色（默认确认），vision/agent 已配置才默认确认
        want = True if role == "text" else bool(existing.roles.get(role))
        if not typer.confirm(f"配置 {role} 角色", default=want):
            return None
        current = existing.roles.get(role)
        default_model = (current.model if current else None) or ROLE_MODEL_SUGGESTIONS[role]
        if not default_model:
            return str(typer.prompt(f"  {role} 模型 ID"))
        return str(typer.prompt(f"  {role} 模型 ID", default=default_model))

    roles: dict[str, RoleConfig | None] = {}
    for role in ("text", "vision", "agent"):
        model = ask_model(role)
        if model is None:
            roles[role] = None
            continue
        roles[role] = RoleConfig(
            provider=proto,
            model=model,
            api_key=api_key,
            base_url=base_url or None,
            max_tokens=8192,
            temperature=0.0,
            seed=42,
        )
    if roles.get("text") is None and roles.get("vision") is None and roles.get("agent") is None:
        rprint("[red]至少需配置一个角色（text 建议必配），已取消。[/red]")
        raise typer.Exit(code=1)

    path = save_llm_file(LLMFileConfig(roles=roles))
    rprint(f"[green]✅ 已保存[/green] {path}（0600）")
    rprint("[blue]下一步:[/blue] agent-eval models test 验证连通性；agent-eval models list 查看")


@models_app.command("list")
def list_models() -> None:
    """查看当前模型配置（api-key 脱敏）。"""
    from agent_eval.config.llm_file import ROLES, llm_file_path, load_llm_file

    cfg = load_llm_file()
    if cfg is None:
        rprint(
            f"[yellow]未配置（{llm_file_path()} 不存在）。运行 [/yellow][bold]agent-eval models set[/bold]"
        )
        raise typer.Exit(code=1)

    table = Table(title="LLM 模型配置")
    table.add_column("角色", style="bold")
    table.add_column("提供商")
    table.add_column("模型")
    table.add_column("Base URL")
    table.add_column("API Key")
    for role in ROLES:
        rc = cfg.roles.get(role)
        if rc is None:
            note = "回退 text" if role == "agent" else "未配置"
            table.add_row(role, f"[dim]{note}[/dim]", "—", "—", "—")
        else:
            table.add_row(
                role, rc.provider, rc.model, rc.base_url or "（官方端点）", _mask(rc.api_key)
            )
    rprint(table)


@models_app.command()
def test() -> None:
    """对已配置角色做连通性测试（真实调用一次对话接口）。"""
    from agent_eval.config.llm import ProviderConfig
    from agent_eval.config.llm_file import ROLES, load_llm_file
    from agent_eval.core.exceptions import AgentEvalError
    from agent_eval.llm.factory import LLMClientFactory
    from agent_eval.llm.models import Message

    cfg = load_llm_file()
    if cfg is None or not any(cfg.roles.get(r) for r in ROLES):
        rprint("[yellow]未配置模型。运行 [/yellow][bold]agent-eval models set[/bold]")
        raise typer.Exit(code=1)

    failed = False
    for role in ROLES:
        rc = cfg.roles.get(role)
        if rc is None:
            rprint(f"[dim]· {role}: 跳过（未配置）[/dim]")
            continue
        try:
            client = LLMClientFactory.create(
                role,
                ProviderConfig(
                    provider=rc.provider,
                    model=rc.model,
                    api_key=rc.api_key,
                    base_url=rc.base_url,
                ),
            )
            start = time.perf_counter()
            resp = client.chat([Message(role="user", content="ping，请只回复 pong")])
            ms = (time.perf_counter() - start) * 1000
            text = (resp.content or "").strip()[:40]
            rprint(f"[green]✅ {role}[/green] {rc.model} — {ms:.0f}ms：「{text}」")
        except AgentEvalError as e:
            failed = True
            rprint(f"[red]❌ {role}[/red] {rc.model} — {e}")
        except Exception as e:  # noqa: BLE001 — 连通性测试需如实报告任何失败
            failed = True
            rprint(f"[red]❌ {role}[/red] {rc.model} — {e}")
    if failed:
        raise typer.Exit(code=1)


@models_app.command("clear")
def models_clear() -> None:
    """删除本地 LLM 配置文件（含 api-key）。"""
    from agent_eval.config.llm_file import llm_file_path

    path = llm_file_path()
    if not path.exists():
        rprint("[yellow]无本地配置可删除。[/yellow]")
        return
    if not typer.confirm(f"确认删除 {path}（含 api-key）", default=False):
        rprint("已取消。")
        return
    path.unlink()
    rprint(f"[green]✅ 已删除[/green] {path}")
