"""查看结果域 — 本地运行浏览与报告直达（F-C-RUNS）。"""

from __future__ import annotations

from typing import Any

from rich import print as rprint

from agent_eval.cli.console.prompts import confirm, select


def main(session: Any) -> None:
    from agent_eval.cli.cmds.open_url import open_target
    from agent_eval.cli.cmds.runs import scan_runs, show_run

    runs = scan_runs()
    if not runs:
        rprint("[yellow]本地无运行记录（workspace/runs/ 为空）。[/yellow]")
        return
    options = [
        f"{r['run_id']}  {r['status']}  任务 {r['tasks']}  R={r['reward']}" for r in runs
    ] + ["返回"]
    pick = select("选择运行", options)
    if pick == "返回":
        return
    run_id = pick.split("  ")[0]
    show_run(run_id)
    if confirm("打开完整报告 (summary.md)?", default=False):
        open_target("report", run_id)
