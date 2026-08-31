"""agent-eval pack — 将手动产出物打包为标准 ExecutionPackage（arch/15 组织约定 2）。"""

from __future__ import annotations

from pathlib import Path

import typer

from agent_eval.cli._common import rprint


def _content_hash(source_dir: Path) -> str | None:
    """计算目录内容的稳定短哈希（SHA256 前 8 位），用于样本内容寻址。

    按「相对路径 + 文件内容」聚合哈希（相对路径排序保证遍历顺序稳定），
    确保同内容同哈希、不同内容不同哈希，不受时间戳/路径位置/遍历顺序影响。
    隐藏文件（.DS_Store 等）排除以提升稳定性。空目录返回 None（调用方回退到目录名）。
    """
    import hashlib

    h = hashlib.sha256()
    files = sorted(
        p
        for p in source_dir.rglob("*")
        if p.is_file() and not any(part.startswith(".") for part in p.relative_to(source_dir).parts)
    )
    if not files:
        return None
    for p in files:
        h.update(p.relative_to(source_dir).as_posix().encode("utf-8"))
        h.update(b"\x00")
        h.update(p.read_bytes())
        h.update(b"\x00")
    return h.hexdigest()[:8]


def pack(
    files: list[str] | None = typer.Option(None, "--files", help="文件路径（可多次指定）"),
    source_dir: str | None = typer.Option(None, "--source-dir", help="源目录路径"),
    task_id: str | None = typer.Option(None, "--task-id", help="任务 ID（默认自动推导）"),
    task_title: str | None = typer.Option(None, "--task-title", help="任务标题"),
    task_subject: str | None = typer.Option(None, "--task-subject", help="任务学科"),
    output_dir: str = typer.Option("./workspace/packages", "--output-dir", help="输出目录"),
    validate: bool = typer.Option(False, "--validate", help="打包后验证完整性"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="详细输出"),
) -> None:
    """将产出物打包为标准 ExecutionPackage。"""
    execute_pack(
        files=files,
        source_dir=source_dir,
        task_id=task_id,
        task_title=task_title,
        task_subject=task_subject,
        output_dir=output_dir,
        validate=validate,
        verbose=verbose,
    )


def execute_pack(
    files: list[str] | None = None,
    source_dir: str | None = None,
    task_id: str | None = None,
    task_title: str | None = None,
    task_subject: str | None = None,
    output_dir: str = "./workspace/packages",
    validate: bool = False,
    verbose: bool = False,
) -> None:
    """打包动作（纯函数；typer.Option 默认值仅经 CLI 分发注入真实值，勿直调绑定）。"""
    from agent_eval.core.logging import setup_logging

    setup_logging(level="DEBUG" if verbose else "INFO")

    # 参数校验：--files 和 --source-dir 二选一
    if not files and not source_dir:
        rprint("[bold red]❌ 请指定 --files 或 --source-dir[/bold red]")
        raise typer.Exit(code=1)
    if files and source_dir:
        rprint("[bold red]❌ --files 和 --source-dir 不能同时指定[/bold red]")
        raise typer.Exit(code=1)

    try:
        from datetime import datetime

        from agent_eval.execution.models import Task
        from agent_eval.storage.builder import PackageBuilder

        # 自动推导 task_id：取末级目录名作为「逻辑课件标识」（跨版本稳定，便于走势聚合）。
        # 内容指纹另存为 content_hash 字段（溯源/版本标记），不混入 task_id。
        # 不同课件若同名，应以 --task-id 显式区分。
        if task_id is None:
            if source_dir:
                task_id = Path(source_dir).resolve().name
            else:
                task_id = f"pack_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        # 自动推导 task_title
        title = task_title or task_id

        # 构建 Task.input
        task_input: dict = {"title": title}
        if task_subject:
            task_input["subject"] = task_subject

        task = Task(id=task_id, input=task_input)
        builder = PackageBuilder()
        pkg_dir = Path(output_dir) / task_id

        # 执行打包
        if source_dir:
            rprint("[blue]模式:[/blue] 目录打包")
            rprint(f"[blue]源目录:[/blue] {source_dir}")
            content_hash = _content_hash(Path(source_dir))
            builder.build_directory(
                task=task,
                source_dir=Path(source_dir),
                package_dir=pkg_dir,
                content_hash=content_hash,
            )
        else:
            rprint("[blue]模式:[/blue] 文件打包")
            rprint(f"[blue]文件数:[/blue] {len(files)}")
            builder.build_inline(
                task=task,
                output_files=[Path(f) for f in files],
                package_dir=pkg_dir,
            )

        # 可选验证
        if validate:
            missing = builder.validate_package(pkg_dir)
            if missing:
                rprint(f"[yellow]⚠ 打包验证：缺少文件 {missing}[/yellow]")
            else:
                rprint("[green]✓ 打包验证通过[/green]")

        rprint(f"[green]✅ 打包完成[/green] → {pkg_dir}")

    except Exception as e:
        rprint(f"[bold red]❌ 打包失败: {e}[/bold red]")
        raise typer.Exit(code=1) from e
