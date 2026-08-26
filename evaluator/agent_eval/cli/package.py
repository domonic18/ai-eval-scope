"""场景包子命令 — init / validate / list / pull。

对齐 13 配置管理设计 §5.5。提供本地包脚手架、校验、列举与从线上拉取能力。
"""

from __future__ import annotations

from pathlib import Path

import typer

from agent_eval.cli._common import Table, rprint

package_app = typer.Typer(name="package", help="场景包管理：init / validate / list / pull")


@package_app.command("init")
def package_init(
    ref: str = typer.Argument(..., help="scenario/package 引用，如 travel-itinerary/quality"),
    output: Path | None = typer.Option(
        None, "--output", "-o", help="输出目录，默认 ./<package_id>/"
    ),
    template: str = typer.Option("courseware", "--template", "-t", help="脚手架模板"),
    force: bool = typer.Option(False, "--force", help="目标目录非空时强制覆盖"),
) -> None:
    """按模板生成场景包目录骨架（含 agent_eval.yaml 清单）。"""
    from agent_eval.packages import parse_ref

    scenario, package_id, _ = parse_ref(ref)
    package_id = package_id or scenario
    root = Path(output) if output else Path.cwd() / package_id
    if root.exists() and any(root.iterdir()) and not force:
        rprint(f"[red]❌ 目标目录非空: {root}（用 --force 覆盖）[/red]")
        raise typer.Exit(code=1)

    for sub in ("rules", "prompts", "datasets"):
        (root / sub).mkdir(parents=True, exist_ok=True)

    manifest = (
        f"# 场景包清单（template={template}）\n"
        f"package:\n"
        f"  id: {package_id}\n"
        f"  scenario: {scenario}\n"
        f"  version: 0.1.0\n"
        f"  name: {package_id}\n"
        f"  description: TODO\n"
        f'  author: ""\n'
        f"  labels: [latest]\n"
    )
    (root / "agent_eval.yaml").write_text(manifest, encoding="utf-8")
    rprint(f"[green]✅ 已创建场景包[/green] → {root}")
    rprint(
        f"[dim]下一步：在 rules/ prompts/ datasets/ 中填充资产，再 `agent-eval package validate {root}`[/dim]"
    )


@package_app.command("validate")
def package_validate(
    path: Path = typer.Argument(..., help="包根目录（含 agent_eval.yaml）"),
) -> None:
    """校验场景包：清单合法、资源目录存在、规则 YAML 可解析。"""
    import yaml

    from agent_eval.core.exceptions import ScenarioPackageValidationError
    from agent_eval.packages import load_manifest

    try:
        manifest = load_manifest(path)
    except ScenarioPackageValidationError as e:
        rprint(f"[red]❌ 清单校验失败: {e}[/red]")
        raise typer.Exit(code=1) from e

    problems: list[str] = []
    for sub in ("rules", "prompts", "datasets"):
        d = path / sub
        if not d.is_dir():
            problems.append(f"缺少资源目录: {sub}/")

    rule_files = sorted((path / "rules").glob("*.yaml")) if (path / "rules").is_dir() else []
    for rf in rule_files:
        try:
            yaml.safe_load(rf.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            problems.append(f"规则 YAML 解析失败 {rf.name}: {e}")

    if problems:
        rprint(f"[red]❌ 校验失败（{len(problems)} 项）:[/red]")
        for p in problems:
            rprint(f"  • {p}")
        raise typer.Exit(code=1)

    rprint(
        f"[green]✅ 校验通过[/green] {manifest.ref} "
        f"(rules={len(rule_files)}, prompts={len(list((path / 'prompts').glob('*.yaml')))})"
    )


@package_app.command("list")
def package_list(
    source: str = typer.Option("all", "--source", "-s", help="all | builtin | local"),
) -> None:
    """列出场景包（内置 / 本地缓存）。"""
    from agent_eval.packages import PackageManager

    if source not in ("all", "builtin", "local"):
        rprint("[red]--source 仅支持 all/builtin/local[/red]")
        raise typer.Exit(code=1)

    pkgs = PackageManager().list(source=source)
    if not pkgs:
        rprint(f"[dim]无场景包（source={source}）[/dim]")
        return

    table = Table(title=f"场景包（{source}，{len(pkgs)} 个）")
    table.add_column("ref", style="cyan")
    table.add_column("名称")
    table.add_column("版本")
    table.add_column("标签")
    table.add_column("来源")
    for p in pkgs:
        table.add_row(
            p.manifest.ref,
            p.manifest.name or p.manifest.id,
            p.manifest.version,
            ",".join(p.manifest.labels) or "—",
            p.source,
        )
    rprint(table)


@package_app.command("pull")
def package_pull(
    ref: str = typer.Argument(..., help="scenario/package:version_or_label"),
    remote: str | None = typer.Option(
        None,
        "--remote",
        help="远端仓库基址（如 http://localhost:9000）；默认读 AGENT_EVAL_REGISTRY_URL",
    ),
) -> None:
    """从线上拉取场景包到本地缓存（~/.agent_eval/packages/）。"""
    from agent_eval.packages import PackageStore, get_remote_client
    from agent_eval.packages.remote_client import HttpRemotePackageClient

    client = HttpRemotePackageClient(remote) if remote else get_remote_client()
    if client is None:
        rprint(
            "[yellow]⚠ 远端拉取未配置。[/yellow]\n"
            "[dim]设置环境变量 AGENT_EVAL_REGISTRY_URL（Web 平台基址）或用 --remote <base_url>。[/dim]"
        )
        raise typer.Exit(code=1)

    try:
        remote_pkg = client.fetch(ref)
    except Exception as e:  # noqa: BLE001
        rprint(f"[red]❌ 拉取失败: {e}[/red]")
        raise typer.Exit(code=1) from e

    root = PackageStore().install(remote_pkg.manifest, dict(remote_pkg.files))
    rprint(f"[green]✅ 已拉取[/green] {remote_pkg.manifest.ref} → {root}")
