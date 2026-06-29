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


@knowledge_app.command("audit")
def knowledge_audit(
    subject: str = typer.Option(None, "--subject", help="指定学科（默认全部，不含 _defaults）"),
    max_len: int = typer.Option(
        4, "--max-len", help="「超短」阈值：裸词字符数 ≤ 该值视为超短（默认 4）"
    ),
    keep_misspellings: bool = typer.Option(
        True,
        help="保留错别字/用字纠正类 pattern（真阳检测）；--no-keep-misspellings 一并删除",
    ),
    weak_anchored: bool = typer.Option(
        True,
        help="清理弱锚定通配（因为.*所以/不是.*而是/购.*买 等功能词·双单字）；--no-weak-anchored 仅清裸词",
    ),
    apply: bool = typer.Option(False, "--apply", help="执行删除并写盘（默认仅审计报告）"),
) -> None:
    """审计 / 清理 misconception 中的「无有效锚定」pattern（误报根因）。

    涵盖两类（根因相同：仅靠短字面子串匹配，正常文本讨论/使用即误报）：
    1. 超短裸词——概念名词（理想/信念/滞后性/价值观）；
    2. 弱锚定通配——`.*` 仅连短片段（因为.*所以/不是.*而是/购.*买/翦.*剪）。

    保留：带字符类/分组/定位的、长裸词的、含内容词的概念辨析（三英.*赵云），以及
    错别字/用字纠正类（真阳）。格式保留（不动注释与缩进）。

    用法：
      agent-eval knowledge audit                       # 仅报告
      agent-eval knowledge audit --apply               # 执行清理（git diff 复核）
      agent-eval knowledge audit --no-weak-anchored    # 仅清超短裸词
    """
    from agent_eval.knowledge.auditor import audit_all

    subjects = [subject] if subject else None
    reports = audit_all(
        max_len=max_len,
        keep_misspellings=keep_misspellings,
        weak_anchored=weak_anchored,
        apply=apply,
        subjects=subjects,
    )

    total_removed = sum(r.removed_count for _, _, r in reports)
    total_kept = sum(r.kept_anchored_or_long for _, _, r in reports)
    mode = (
        "[bold red]已写盘[/bold red]" if apply else "[dim]（dry-run 未写盘，加 --apply 执行）[/dim]"
    )

    rprint(
        f"\n[bold green]✅ 审计完成[/bold green] {mode} | "
        f"删除 {total_removed} 条无有效锚定 pattern | 保留 {total_kept} 条"
        f"（max_len={max_len}, keep_misspellings={keep_misspellings}, "
        f"weak_anchored={weak_anchored}）\n"
    )
    rprint("[bold]按学科分布：[/bold]")
    for subject_name, _, report in reports:
        rprint(
            f"  {subject_name:12} 删除 {report.removed_count:4} | "
            f"保留 {report.kept_anchored_or_long:4}"
        )
    if apply and total_removed:
        rprint("\n[dim]已修改对应 *.yaml，请用 git diff 复核改动。[/dim]")
    rprint("")


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
