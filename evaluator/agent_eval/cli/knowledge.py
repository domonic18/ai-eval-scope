"""知识点完善子命令 — 提取、转换、合并、查看。"""

from __future__ import annotations

from pathlib import Path

import typer

from agent_eval.cli._common import rprint

knowledge_app = typer.Typer(name="knowledge", help="知识点数据完善：提取、转换、合并")


@knowledge_app.command("convert")
def knowledge_convert(
    source: str = typer.Option(
        ..., "--source", "-s", help="结构化数据源（periodic_table/nist_codata）"
    ),
    field: str = typer.Option(..., "--field", "-f", help="字段（constants/domain_facts）"),
    subject: str = typer.Option(..., "--subject", help="目标学科（如 chemistry）"),
    limit: int = typer.Option(None, "--limit", help="限制处理数量"),
    apply: bool = typer.Option(False, "--apply", help="转换后自动合并到 knowledge yaml"),
    json_path: str = typer.Option(None, "--json-path", help="数据源文件路径（如周期表 JSON）"),
) -> None:
    """从结构化数据源转换知识点（如周期表→constants）。"""
    from agent_eval.knowledge.pipeline import KnowledgePipeline

    try:
        kwargs = {}
        if json_path:
            kwargs["json_path"] = json_path
        pipe = KnowledgePipeline()
        result = pipe.run(
            source_name=source,
            field=field,
            subject=subject,
            limit=limit,
            apply=apply,
            **kwargs,
        )
        rprint(f"[bold green]✅ 转换完成[/bold green] → {result}")
        if apply:
            rprint(f"[dim]已合并到 {subject}.yaml[/dim]")
    except Exception as e:
        rprint(f"[bold red]❌ 转换失败: {e}[/bold red]")
        raise typer.Exit(code=1) from e


@knowledge_app.command("extract")
def knowledge_extract(
    source: str = typer.Option(..., "--source", "-s", help="评测题数据源（arc/cmmlu）"),
    field: str = typer.Option(..., "--field", "-f", help="字段（misconceptions/constants）"),
    subject: str = typer.Option(..., "--subject", help="目标学科"),
    limit: int = typer.Option(None, "--limit", help="限制题数"),
    apply: bool = typer.Option(False, "--apply", help="提取后自动合并到 knowledge yaml"),
    data_dir: str = typer.Option(None, "--data-dir", help="数据集目录"),
    subjects: str = typer.Option(None, "--subjects", help="学科筛选（逗号分隔，cmmlu 用）"),
    provider: str = typer.Option(None, "--provider", help="LLM provider 名"),
) -> None:
    """从评测题 LLM 提取知识点（misconceptions/constants）。"""
    from agent_eval.knowledge.pipeline import KnowledgePipeline

    try:
        kwargs = {}
        if data_dir:
            kwargs["data_dir"] = data_dir
        if subjects:
            kwargs["subjects"] = subjects.split(",")
        if provider:
            kwargs["provider"] = provider
        pipe = KnowledgePipeline()
        result = pipe.run(
            source_name=source,
            field=field,
            subject=subject,
            limit=limit,
            apply=apply,
            **kwargs,
        )
        rprint(f"[bold green]✅ 提取完成[/bold green] → {result}")
        if apply:
            rprint(f"[dim]已合并到 {subject}.yaml[/dim]")
    except Exception as e:
        rprint(f"[bold red]❌ 提取失败: {e}[/bold red]")
        raise typer.Exit(code=1) from e


@knowledge_app.command("merge")
def knowledge_merge(
    input_file: Path = typer.Option(..., "--input", "-i", help="待合并的 YAML 文件"),
    subject: str = typer.Option(..., "--subject", help="目标学科"),
    field: str = typer.Option(None, "--field", "-f", help="字段（不指定则从 YAML 推断）"),
    strategy: str = typer.Option("skip", "--strategy", help="去重策略：skip/replace"),
    dry_run: bool = typer.Option(False, "--dry-run", help="只报告不写盘"),
) -> None:
    """合并提取产物到 knowledge yaml。"""
    from agent_eval.knowledge.merger import KnowledgeMerger
    from agent_eval.knowledge.models import KnowledgePatch

    try:
        patch = KnowledgePatch.from_yaml(input_file)
        merger = KnowledgeMerger()
        stats = merger.merge(patch, subject=subject, strategy=strategy, dry_run=dry_run)
        action = "[dim]（dry-run 未写盘）" if dry_run else f"→ {subject}.yaml"
        rprint(
            f"[bold green]✅ 合并完成[/bold green] {action} | "
            f"新增 {stats['added']} | 跳过 {stats['skipped']} | "
            f"替换 {stats['replaced']} | 总计 {stats['total']}"
        )
    except Exception as e:
        rprint(f"[bold red]❌ 合并失败: {e}[/bold red]")
        raise typer.Exit(code=1) from e


@knowledge_app.command("list")
def knowledge_list(
    subject: str = typer.Option(..., "--subject", help="学科"),
    field: str = typer.Option(None, "--field", "-f", help="字段（不指定则列出全部）"),
) -> None:
    """查看现有 knowledge 数据。"""
    from agent_eval.knowledge.merger import KnowledgeMerger

    merger = KnowledgeMerger()
    if field:
        items = merger.list_field(subject, field)
        rprint(f"\n[bold blue]{subject}.{field}（{len(items)} 条）[/bold blue]\n")
        for item in items:
            name = item.get("name") or item.get("pattern") or item.get("id", "?")
            rprint(f"  • [cyan]{name}[/cyan]")
    else:
        from agent_eval.knowledge.manager import KnowledgeBaseManager

        data = KnowledgeBaseManager().load(subjects=[subject])
        for f in ["constants", "misconceptions", "domain_facts"]:
            if f == "domain_facts":
                count = len(data.get(f, {}))
            else:
                count = len(data.get(f, []))
            rprint(f"  {f}: {count} 条")
    rprint("")
