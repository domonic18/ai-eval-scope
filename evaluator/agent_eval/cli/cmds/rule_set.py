"""规则集管理子命令 — 校验、模板浏览。

版本管理（history/diff/apply/rollback）已迁移至 git，本子命令组仅保留只读操作。
"""

from __future__ import annotations

import typer

from agent_eval.cli._common import rprint

rule_app = typer.Typer(name="rule-set", help="规则集管理：校验、模板浏览")


@rule_app.command("validate")
def rule_validate(
    rule_set_path: str = typer.Option(..., "--rule-set", "-r", help="规则集文件路径"),
    resolve_templates: bool = typer.Option(
        True, "--resolve-templates/--no-resolve", help="解析模板引用"
    ),
) -> None:
    """验证规则集语义正确性。"""
    from agent_eval.config.loader import ConfigLoader
    from agent_eval.rules.validation import RuleSetValidator

    try:
        rs = ConfigLoader.load_rule_set(
            rule_set_path,
            resolve_templates=resolve_templates,
        )
        errors = RuleSetValidator().validate(rs)
        if errors:
            rprint("[bold red]❌ 规则集语义校验失败:[/bold red]")
            for e in errors:
                rprint(f"  • [red]{e}[/red]")
            raise typer.Exit(code=1)
        rprint(f"[green]✅ 规则集校验通过: {rule_set_path}[/green]")
    except Exception as e:
        rprint(f"[bold red]❌ 校验失败: {e}[/bold red]")
        raise typer.Exit(code=1) from e


@rule_app.command("list-templates")
def rule_list_templates(
    rule_set_path: str = typer.Option(..., "--rule-set", "-r", help="规则集文件路径"),
) -> None:
    """列出规则集中定义的模板。"""
    from agent_eval.config.loader import ConfigLoader

    try:
        rs = ConfigLoader.load_rule_set(rule_set_path, resolve_templates=False)
        if not rs.templates:
            rprint("[dim]本规则集未定义模板[/dim]")
            return

        rprint("\n[bold blue]═══ 规则模板 ═══[/bold blue]\n")
        for t in rs.templates:
            rprint(f"  • [cyan]{t.id}[/cyan]: {t.name} ({t.evaluator})")
        rprint("")
    except Exception as e:
        rprint(f"[bold red]❌ list-templates 失败: {e}[/bold red]")
        raise typer.Exit(code=1) from e
