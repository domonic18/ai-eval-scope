"""数据集管理子命令 — 下载、查看。"""

from __future__ import annotations

from pathlib import Path

import typer

from agent_eval.cli._common import Table, rprint

dataset_app = typer.Typer(name="dataset", help="评测数据集管理：下载、查看")


@dataset_app.command("download")
def dataset_download(
    name: str = typer.Argument(
        ..., help="数据集标识。预置名（如 ceval）或完整 repo id（如 opencompass/ceval-exam）"
    ),
    source: str | None = typer.Option(
        None,
        "--source",
        "-s",
        help="下载源：huggingface/hf 或 modelscope/ms。默认读 AGENT_EVAL_DATASET_SOURCE",
    ),
    output: Path | None = typer.Option(
        None, "--output", "-o", help="下载目录。默认 {WORKSPACE_DIR}/datasets/{name}"
    ),
    revision: str | None = typer.Option(
        None, "--revision", "-r", help="版本标识。HF 为 commit/branch/tag，MS 为版本号"
    ),
    token: str | None = typer.Option(None, "--token", help="访问 token。默认读对应源的环境变量"),
    force: bool = typer.Option(False, "--force", help="目标目录已存在时强制重新下载"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """从 HuggingFace / ModelScope 下载评测数据集到本地 workspace。"""
    from agent_eval.core.logging import setup_logging
    from agent_eval.datasets import DatasetManager
    from agent_eval.datasets.registry import lookup

    setup_logging(level="DEBUG" if verbose else "INFO")
    try:
        entry = lookup(name)
        label = entry.name if entry else name
        display = entry.description if entry else "(用户指定 repo id)"
        rprint(f"[bold blue]📥 下载数据集:[/bold blue] {label} — {display}")
        target = DatasetManager().download(
            name=name,
            source=source,
            output=output,
            revision=revision,
            token=token,
            force=force,
        )
        rprint(f"[bold green]✅ 下载完成[/bold green] → {target}")
        rprint(f"[dim]manifest: {target / '_dataset_manifest.json'}[/dim]")
    except Exception as e:
        rprint(f"[bold red]❌ 下载失败: {e}[/bold red]")
        raise typer.Exit(code=1) from e


@dataset_app.command("list")
def dataset_list(
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """列出数据集索引中所有可下载的数据集（来源：assets/datasets/dataset_index.yaml）。"""
    from agent_eval.datasets import list_datasets

    datasets = list_datasets()
    if not datasets:
        rprint("[dim]数据集索引为空[/dim]")
        return

    table = Table(title=f"评测数据集索引（{len(datasets)} 个）")
    table.add_column("ID", style="cyan")
    table.add_column("名称")
    table.add_column("类别")
    table.add_column("HF repo", style="green")
    table.add_column("MS repo", style="green")
    for e in datasets.values():
        table.add_row(e.id, e.name, e.category, e.hf_id or "—", e.ms_id or "—")
    rprint(table)
