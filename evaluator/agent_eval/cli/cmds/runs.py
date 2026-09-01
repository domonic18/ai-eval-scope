"""agent-eval runs — 本地运行结果浏览（list / show，arch/15 §7.2）。

数据零新存储：``list`` 扫描 ``workspace/runs/``（manifest + summary 直接读取），
``show`` 直读 run 目录并按 ``metric_definitions`` 动态渲染指标（不硬编码）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer

from agent_eval.cli._common import Table, rprint

runs_app = typer.Typer(name="runs", help="本地运行结果浏览：list / show")


def _workspace_root() -> Path:
    from agent_eval.config.paths import paths

    return paths.default_workspace


def _load_json(path: Path) -> dict[str, Any]:
    try:
        data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        return data
    except (OSError, ValueError):
        return {}


def _reward_of(summary: dict[str, Any]) -> str:
    """从场景化指标 dict 提取 Reward 类指标（键形如 ``<scenario>:reward``）。"""
    metrics = summary.get("metrics", {})
    for key, value in metrics.items():
        if str(key).endswith(":reward") or key == "reward":
            return f"{float(value):.2f}"
    return "—"


def _last_error(run_dir: Path) -> str:
    """agent_logs 里最后一条 error 事件的 error_message（无则空串）。"""
    logs = run_dir / "agent_logs"
    if not logs.is_dir():
        return ""
    for log_file in sorted(logs.glob("*.jsonl"), reverse=True):
        try:
            lines = log_file.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        for line in reversed(lines):
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if event.get("event") == "error" and event.get("error_message"):
                return str(event["error_message"])
    return ""


def _run_status(
    run_dir: Path, manifest: dict[str, Any], summary: dict[str, Any]
) -> tuple[str, str]:
    """推导运行状态与失败原因：(状态, error_message)。"""
    error = _last_error(run_dir)
    if summary:
        return "已评估", error
    if manifest:
        return ("已执行⚠" if error else "已执行"), error
    if error:
        return "执行失败", error
    return "中断", error


def scan_runs(ws: Path | None = None) -> list[dict[str, Any]]:
    """扫描 workspace/runs/ 下的运行目录（新→旧），读取 manifest 与 summary。"""
    root = (ws or _workspace_root()) / "runs"
    if not root.is_dir():
        return []
    runs: list[dict[str, Any]] = []
    for run_dir in sorted((d for d in root.iterdir() if d.is_dir()), reverse=True):
        manifest = _load_json(run_dir / "run_manifest.json")
        summary = _load_json(run_dir / "reports" / "summary.json")
        status, error = _run_status(run_dir, manifest, summary)
        runs.append(
            {
                "run_id": run_dir.name,
                "mode": manifest.get("mode", "—"),
                "package_ref": manifest.get("package_ref", "—"),
                "tasks": summary.get("total_samples", manifest.get("total_tasks", "—")),
                "reward": _reward_of(summary) if summary else "—",
                "status": status,
                "error": error,
                "has_summary": bool(summary),
                "dir": str(run_dir),
            }
        )
    return runs


def list_runs() -> list[dict[str, Any]]:
    """列出本地运行（纯函数动作，workbench 复用）。"""
    from agent_eval.cli.console.output import emit_json, is_json

    runs = scan_runs()
    if is_json():
        emit_json({"runs": runs})
        return runs
    if not runs:
        rprint("[yellow]本地无运行记录（workspace/runs/ 为空）。[/yellow]")
        return runs
    table = Table(title=f"本地运行（{len(runs)} 次）")
    table.add_column("run_id", style="cyan")
    table.add_column("模式")
    table.add_column("状态")
    table.add_column("包")
    table.add_column("任务数", justify="right")
    table.add_column("Reward", justify="right")
    for r in runs:
        table.add_row(
            r["run_id"], r["mode"], r["status"], r["package_ref"], str(r["tasks"]), r["reward"]
        )
    rprint(table)
    rprint("[dim]详情: agent-eval runs show <run_id>[/dim]")
    return runs


@runs_app.command("list")
def runs_list() -> None:
    """列出本地运行（workspace/runs/）。"""
    list_runs()


def show_run(run_id: str) -> None:
    """展示单次运行详情（纯函数动作，workbench 复用）。"""
    from agent_eval.cli.console.output import emit_json, is_json

    run_dir = _workspace_root() / "runs" / run_id
    if not run_dir.is_dir():
        rprint(f"[red]运行目录不存在: {run_dir}[/red]")
        raise typer.Exit(code=1)

    manifest = _load_json(run_dir / "run_manifest.json")
    summary = _load_json(run_dir / "reports" / "summary.json")
    if is_json():
        emit_json({"run_id": run_id, "manifest": manifest, "summary": summary})
        return

    rprint(f"[bold]═══ 运行 {run_id} ═══[/bold]")
    if manifest:
        rprint(
            f"  模式: [cyan]{manifest.get('mode', '—')}[/cyan]   "
            f"包: [cyan]{manifest.get('package_ref', '—')}[/cyan]   "
            f"SUT: [cyan]{(manifest.get('sut') or {}).get('name', '—')}[/cyan]"
        )
    if not summary:
        status, error = _run_status(run_dir, manifest, summary)
        rprint(f"  状态: [yellow]{status}[/yellow]（无 reports/summary.json）")
        if error:
            rprint(f"  失败原因: [red]{error}[/red]")
            if "凭证未配置" in error:  # 常见根因：给出录入命令
                import re

                for ref_field in re.findall(r"凭证未配置: (\S+?)（", error):
                    rprint(f"  [dim]→ 录入: agent-eval secrets set {ref_field}[/dim]")
        pkg_dir = run_dir / "packages"
        n_pkgs = len(list(pkg_dir.iterdir())) if pkg_dir.is_dir() else 0
        if manifest:
            rprint(
                f"  [dim]已执行 {n_pkgs} 个任务包；评估: agent-eval eval "
                f"--package-dir {pkg_dir} --package <场景包>[/dim]"
            )
        else:
            rprint("  [dim]执行未写运行清单（早期失败）——修复后重跑；结构化日志: agent_logs/[/dim]")
        return

    # 指标：按 metric_definitions 动态渲染（id/name/threshold），未覆盖的键兜底展示
    table = Table(title="指标")
    table.add_column("指标", style="bold")
    table.add_column("值", justify="right")
    table.add_column("阈值", justify="right")
    table.add_column("状态")
    metrics = summary.get("metrics", {})
    defs = summary.get("metric_definitions") or []
    rendered: set[str] = set()
    for md in defs:
        mid = md.get("id")
        if mid is None or mid not in metrics:
            continue
        rendered.add(mid)
        threshold = md.get("threshold")
        value = float(metrics[mid])
        status = "—" if threshold is None else ("✅" if value >= float(threshold) else "❌")
        table.add_row(
            md.get("name") or mid,
            f"{value:.3f}",
            "—" if threshold is None else str(threshold),
            status,
        )
    for mid, value in metrics.items():
        if mid not in rendered:
            table.add_row(mid, f"{float(value):.3f}", "—", "—")

    rprint(table)

    breakdown = summary.get("failure_breakdown") or {}
    if breakdown:
        rprint("[bold red]失败 Top:[/bold red]")
        for cid, count in sorted(breakdown.items(), key=lambda x: -x[1])[:10]:
            rprint(f"  • [red]{cid}[/red]: {count} 次")

    report_md = run_dir / "reports" / "summary.md"
    if report_md.exists():
        rprint(f"[dim]完整报告: {report_md}（agent-eval open report {run_id}）[/dim]")


@runs_app.command("show")
def runs_show(
    run_id: str | None = typer.Argument(
        None, help="运行 ID（workspace/runs/{run_id}）；缺省进入交互选择"
    ),
) -> None:
    """查看单次运行的指标 / 失败明细 / 报告位置。"""
    show_run(select_run_id() if run_id is None else run_id)


def select_run_id(env_key: str = "AGENT_EVAL_RUN_ID") -> str:
    """run_id 缺省时的交互选择（--no-input 下 env 唯一前缀旁路）。"""
    from agent_eval.cli.console.prompts import resolve_bypass, select

    found = scan_runs()
    if not found:
        rprint("[yellow]本地无运行记录（workspace/runs/ 为空，先 agent-eval pipeline）。[/yellow]")
        raise typer.Exit(code=1)
    options = [f"{r['run_id']}  {r['status']}  R={r['reward']}" for r in found]
    bypassed = resolve_bypass(env_key, options)
    return bypassed.split("  ")[0] if bypassed else select("选择运行", options).split("  ")[0]
