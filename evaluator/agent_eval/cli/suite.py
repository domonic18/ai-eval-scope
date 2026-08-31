"""agent-eval suite — 声明式评测矩阵（arch/13 §二十一，W6）。

suite.yaml 声明「不同考卷 × 不同环境」的批量运行，一次展开、逐项执行、
汇总对照。runs 条目字段：package（场景包引用，必填）、task_set（包内名，
缺省 manifest.default_task_set）、sut（包内系统名，缺省唯一系统）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import typer
import yaml
from rich import print as rprint
from rich.table import Table

suite_app = typer.Typer(help="声明式评测矩阵（suite.yaml 批量运行与对照）")


def _load_suite(path: Path) -> dict[str, Any]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as e:
        rprint(f"[red]suite 文件读取失败: {e}[/red]")
        raise typer.Exit(code=1) from e
    runs = data.get("runs")
    if not isinstance(runs, list) or not runs:
        rprint(f"[red]suite 缺少 runs 列表: {path}[/red]")
        raise typer.Exit(code=1)
    return data


@suite_app.command("plan")
def plan(suite_file: str = typer.Option(..., "--file", help="suite.yaml 路径")) -> None:
    """展开矩阵预览（不执行）：显示每条 run 的包/考卷/SUT 解析结果。"""
    from agent_eval.packages.assets import resolve_sut_configs_dir, resolve_task_set_path
    from agent_eval.packages.manager import PackageManager

    data = _load_suite(Path(suite_file))
    table = Table(title=f"suite: {data.get('suite', '(unnamed)')}")
    table.add_column("#", justify="right")
    table.add_column("package")
    table.add_column("task_set")
    table.add_column("sut_configs")

    mgr = PackageManager()
    for i, entry in enumerate(data["runs"], 1):
        try:
            pkg = mgr.resolve_ref(str(entry["package"]))
            ts = resolve_task_set_path(pkg, entry.get("task_set"))
            sut_dir = resolve_sut_configs_dir(pkg)
            table.add_row(str(i), pkg.manifest.ref, ts.stem, str(sut_dir.name))
        except Exception as e:  # noqa: BLE001 — 预览模式逐项报告
            table.add_row(str(i), str(entry.get("package")), f"[red]{e}[/red]", "—")
    rprint(table)


@suite_app.command("run")
def run_suite(
    suite_file: str = typer.Option(..., "--file", help="suite.yaml 路径"),
    dry_run: bool = typer.Option(False, "--dry-run", help="只打印将执行的 run 命令"),
) -> None:
    """逐项执行矩阵（串行），结束后输出汇总对照表。"""
    from agent_eval.cli._stages import execute_stage, resolve_run_inputs
    from agent_eval.core.exceptions import AgentEvalError
    from agent_eval.storage.package import generate_run_id

    data = _load_suite(Path(suite_file))
    results: list[dict[str, Any]] = []

    for i, entry in enumerate(data["runs"], 1):
        label = f"[{i}/{len(data['runs'])}]"
        try:
            inputs = resolve_run_inputs(
                str(entry["package"]),
                task_set=entry.get("task_set"),
                task_select=str(entry.get("task")) if entry.get("task") else None,
                sut_name=entry.get("sut"),
            )
            pkg = inputs.resolved_pkg
            assert pkg is not None  # suite 条目必为包引用

            rprint(
                f"\n{label} {pkg.manifest.ref} | "
                f"task_set={inputs.task_set_path.stem} | sut={inputs.sut.name}"
            )
            if dry_run:
                results.append(
                    {
                        "ref": pkg.manifest.ref,
                        "ts": inputs.task_set_path.stem,
                        "sut": inputs.sut.name,
                        "ok": 0,
                        "total": 0,
                    }
                )
                continue

            run_id = generate_run_id()
            packages = execute_stage(
                inputs,
                run_id=run_id,
                workspace_root=Path("./workspace"),
                mode="run",
            )
            ok = sum(1 for p in packages if p.manifest.status == "success")
            results.append(
                {
                    "ref": pkg.manifest.ref,
                    "ts": inputs.task_set_path.stem,
                    "sut": inputs.sut.name,
                    "ok": ok,
                    "total": len(packages),
                }
            )
        except AgentEvalError as e:
            rprint(f"[red]{label} 失败: {e}[/red]")
            results.append(
                {
                    "ref": str(entry.get("package")),
                    "ts": "—",
                    "sut": "—",
                    "ok": 0,
                    "total": 0,
                    "error": str(e),
                }
            )

    table = Table(title=f"suite 结果: {data.get('suite', '(unnamed)')}")
    table.add_column("package")
    table.add_column("task_set")
    table.add_column("sut")
    table.add_column("成功/总数", justify="right")
    for r in results:
        color = (
            "green"
            if r["ok"] == r["total"] and r["total"] > 0
            else ("red" if "error" in r else "yellow")
        )
        table.add_row(r["ref"], r["ts"], r["sut"], f"[{color}]{r['ok']}/{r['total']}[/{color}]")
    rprint(table)
