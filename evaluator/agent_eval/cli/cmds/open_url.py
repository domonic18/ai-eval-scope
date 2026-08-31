"""agent-eval open — 浏览器直达（requirement/04 F-C-OPEN，arch/15 §5.3 / D-CLI-5）。

单出口设计：全部打开动作经 ``open_url``/``open_path``，便于测试 mock（NF-C-05）。
``webbrowser`` 原生尊重 ``$BROWSER``；无浏览器环境（SSH / 容器）降级打印 URL。
P0 支持本地报告与平台首页；run/scenario/secrets/keys 等平台深链待前端路由对齐后（P1）开放。
"""

from __future__ import annotations

import os
import subprocess
import sys

import typer
from rich import print as rprint

__all__ = ["open_path", "open_target", "open_url"]

_PLATFORM_TARGETS = ("platform", "docs")


def open_url(url: str) -> bool:
    """用系统浏览器打开 URL（尊重 $BROWSER）；失败降级打印 URL，返回是否已打开。"""
    import webbrowser

    if webbrowser.open(url):
        rprint(f"[green]✅ 已打开浏览器[/green] {url}")
        return True
    rprint(f"[yellow]⚠ 无可用浏览器，请手动打开:[/yellow] {url}")
    return False


def open_path(path: str) -> None:
    """用系统默认程序打开本地文件（报告等）。"""
    if sys.platform == "darwin":
        subprocess.Popen(["open", path])  # noqa: S603 - 固定参数
    elif sys.platform == "win32":
        os.startfile(path)  # noqa: S606
    else:
        subprocess.Popen(["xdg-open", path])  # noqa: S603 - 固定参数
    rprint(f"[green]✅ 已打开[/green] {path}")


def open_target(target: str, run_id: str | None = None) -> None:
    """``open <target>`` 动作（纯函数，命令层与 workbench 复用）。"""
    if target == "report":
        if not run_id:
            rprint("[red]❌ open report 需要 run_id[/red]")
            raise typer.Exit(code=2)
        from agent_eval.config.paths import paths

        report = paths.default_workspace / "runs" / run_id / "reports" / "summary.md"
        if not report.exists():
            rprint(f"[red]❌ 报告不存在: {report}[/red]")
            raise typer.Exit(code=1)
        open_path(str(report))
        return

    if target in _PLATFORM_TARGETS:
        host = os.environ.get("AGENT_EVAL_HOST", "").rstrip("/")
        if not host:
            rprint("[red]❌ 未配置平台地址（AGENT_EVAL_HOST）。[/red]")
            rprint("[dim]Sprint 11: agent-eval auth login；或先在 .env 配置 AGENT_EVAL_HOST[/dim]")
            raise typer.Exit(code=2)
        open_url(host if target == "platform" else f"{host}/docs")
        return

    rprint(
        f"[yellow]⚠ open {target} 将在前端路由对齐后开放（Sprint 11）；"
        f"当前可用: {'/'.join(('report', *_PLATFORM_TARGETS))}[/yellow]"
    )
    raise typer.Exit(code=1)
