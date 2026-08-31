"""CLI 引导与轻量顶层命令 — app 装配、全局参数、version / start / open / doctor。

其余顶层命令（pack / eval / run / pipeline / upload）在 ``cmds/`` 各模块定义，
由 ``agent_eval.cli`` 包统一注册（唯一装配点，arch/15 §2.2 组织约定 1）。
"""

from __future__ import annotations

import os

import typer
from dotenv import load_dotenv

from agent_eval.cli._common import rprint

# 在任何配置解析之前加载 .env
load_dotenv()

# 触发所有内置评估器注册（plugins/ 下的插件也会在此自动发现）
# 需要先 load_dotenv() 再导入，故 suppress E402
import agent_eval.evaluation.evaluators  # noqa: E402, F401

app = typer.Typer(
    name="agent-eval",
    help="Agent 能力评估系统 — 基于 Agent-Driven 架构的评测框架",
    no_args_is_help=True,
)


@app.callback()
def _global(
    output_format: str = typer.Option(
        "text", "--output-format", help="text（人读）| json（机器可读，stdout 仅 JSON）"
    ),
    no_input: bool = typer.Option(
        False, "--no-input", help="禁一切交互（缺失必需输入即 exit 2，CI 用）"
    ),
) -> None:
    """全局参数：输出形态与交互开关（F-C-INTEG-01/02）。"""
    from agent_eval.cli.console import output

    if output_format not in ("text", "json"):
        rprint("[red]--output-format 仅支持 text|json[/red]")
        raise typer.Exit(code=2)
    output.set_output_format(output_format)
    if no_input:
        os.environ["AGENT_EVAL_NO_INPUT"] = "1"


@app.command()
def version() -> None:
    """显示版本信息。"""
    from agent_eval import __version__

    rprint(f"agent-eval v{__version__}")


@app.command()
def start(
    domain: str = typer.Option(None, "--domain", help="直达工作域：scn | exec | runs | account"),
) -> None:
    """交互式评测工作台（向导式覆盖评测全生命周期，Sprint 10）。"""
    from agent_eval.cli.workbench.session import WorkbenchSession

    WorkbenchSession().run(domain)


@app.command(name="open")
def open_(
    target: str = typer.Argument(..., help="platform | report | docs"),
    run_id: str | None = typer.Argument(None, help="目标 run_id（open report <run_id> 必填）"),
) -> None:
    """浏览器直达：平台首页 / 本地报告（arch/15 §5.3）。"""
    from agent_eval.cli.cmds.open_url import open_target

    open_target(target, run_id)


@app.command()
def doctor() -> None:
    """一键自检：平台 / 模型 / 凭证 / 场景包 / workspace / 依赖 extras（F-C-CONFIG-02）。"""
    from agent_eval.cli.cmds.doctor import doctor_action

    doctor_action()


if __name__ == "__main__":
    app()
