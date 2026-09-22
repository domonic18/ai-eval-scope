"""执行评测域 — 五步选择 + 摘要确认 + 等价命令（F-C-EXEC）。

向导最终以与命令行相同的参数对象调用 ``main.pipeline/run``（双前端同构，
组织约定 3）；等价命令由 ``console/equiv`` 从同一参数组装，天然不漂移。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from rich import print as rprint

from agent_eval.cli.console.equiv import pipeline_argv, render, run_argv
from agent_eval.cli.console.prompts import confirm, select
from agent_eval.execution.registry import SCHEDULED_CHANNELS


def _count_tasks(path: Path) -> int:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return len(data.get("tasks", []))
    except Exception:  # noqa: BLE001 — 展示用途，解析失败按 0 计
        return 0


def _sut_channel(path: Path) -> str:
    """读 sut_configs 的 channel 字段（列表标注与预检；解析失败按空串计）。

    容错 yaml 直读而非 SUTRegistry.load——后者遇未定义 ``${VAR}`` 会抛错，
    会让一个文件的 env 问题炸掉整个选择列表；权威拦截仍在执行工厂与落盘门禁。
    """
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return str((data.get("sut") or {}).get("channel", ""))
    except Exception:  # noqa: BLE001 — 展示用途
        return ""


def main(session: Any) -> None:
    from agent_eval.packages import PackageManager

    pkgs = PackageManager().list()
    if not pkgs:
        rprint("[red]未发现场景包。[/red]")
        return
    options = [f"{p.manifest.ref}  ({p.source})" for p in pkgs] + ["返回"]
    pick = select("选择场景包", options)
    if pick == "返回":
        return
    ref = pick.split("  (")[0]
    resolved = next(p for p in pkgs if p.manifest.ref == ref)
    session.ctx.active_package = ref

    ts_files = sorted(resolved.root.glob("task_sets/*.yaml"))
    if not ts_files:
        rprint("[yellow]包内无考卷（eval-only 场景请走 pack → eval 流程）。[/yellow]")
        return
    default_ts = resolved.manifest.default_task_set or ts_files[0].stem
    task_set = select(
        "选择考卷",
        [f"{f.stem}（{_count_tasks(f)} 任务）" for f in ts_files],
        default=default_ts,
    ).split("（")[0]
    session.ctx.active_task_set = task_set

    sut_files = sorted(resolved.root.glob("sut_configs/*.yaml"))
    if not sut_files:
        rprint("[yellow]包内无 SUT 接入（eval-only 场景请走 pack → eval 流程）。[/yellow]")
        return
    channels = {f.stem: _sut_channel(f) for f in sut_files}
    sut = select("选择 SUT", [f"{stem}（{ch or '未知'}）" for stem, ch in channels.items()])
    sut = sut.split("（")[0]
    # 通道排期前置预检：答完 2 个交互即见错，不等到执行摘要之后的工厂报错
    if channels[sut] not in SCHEDULED_CHANNELS:
        rprint(
            f"[red]通道 {channels[sut]!r} 预留未排期（本期排期通道 "
            f"{'、'.join(SCHEDULED_CHANNELS)}）——"
            "请先把 sut_configs 的 channel 修正为排期通道（可在工作台会话中"
            "让 Agent 重新探测修正）。[/red]"
        )
        return
    session.ctx.active_sut = sut

    rs_files = sorted(resolved.root.glob("rules/*.yaml"))
    default_rs = resolved.manifest.default_rule_set or (rs_files[0].stem if rs_files else None)
    rule_set = (
        select("选择规则集", [f.stem for f in rs_files], default=default_rs) if rs_files else None
    )

    mode = select("执行模式", ["pipeline（执行 + 评估 + 报告）", "run（仅执行）"])

    # 日志档位（F-C-EXEC-07 三形态同源：CLI/向导/Agent 会话共用一档位语义）
    level_options = [
        "normal（默认进度）",
        "verbose（SUT 请求/judge 过程事件）",
        "debug（全量原文日志）",
        "quiet（仅结果行，CI 友好）",
    ]
    log_level = select("日志档位", level_options, default=level_options[0]).split("（")[0]

    argv = (
        pipeline_argv(
            package=ref,
            task_set=task_set,
            sut_name=sut,
            rule_set=rule_set,
            **({"log_level": log_level} if log_level != "normal" else {}),
        )
        if mode.startswith("pipeline")
        else run_argv(
            package=ref,
            task_set=task_set,
            sut_name=sut,
            **({"log_level": log_level} if log_level != "normal" else {}),
        )
    )
    rprint("[bold]── 执行摘要 ──[/bold]")
    rprint(f"  包: [cyan]{ref}[/cyan]   考卷: [cyan]{task_set}[/cyan]   SUT: [cyan]{sut}[/cyan]")
    if rule_set:
        rprint(f"  规则集: [cyan]{rule_set}[/cyan]   ")
    rprint(f"  模式: [cyan]{mode.split('（')[0]}[/cyan]")
    rprint(f"  [dim]等价命令: {render(argv)}[/dim]")
    if not confirm("开始执行?", default=True):
        rprint("[dim]已取消。[/dim]")
        return

    from agent_eval.cli.cmds.execute import execute_pipeline, execute_run

    if mode.startswith("pipeline"):
        execute_pipeline(
            package=ref, task_set=task_set, sut_name=sut, rule_set=rule_set, log_level=log_level
        )
    else:
        execute_run(package=ref, task_set=task_set, sut_name=sut, log_level=log_level)
