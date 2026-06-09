"""CLI 入口 — typer 应用框架。

注册 eval、run、pipeline、serve、index 等子命令。
"""

from __future__ import annotations

import typer
from rich import print as rprint

app = typer.Typer(
    name="agent-eval",
    help="Agent 能力评估系统 — 基于 Agent-Driven 架构的评测框架",
    no_args_is_help=True,
)


@app.command()
def eval(
    package_dir: str = typer.Option(..., "--package-dir", help="ExecutionPackage 目录路径"),
    rule_set: str = typer.Option(..., "--rule-set", help="规则集文件路径"),
    output_dir: str | None = typer.Option(None, "--output-dir", help="输出目录"),
    eval_mode: str = typer.Option("pipeline", "--eval-mode", help="评估模式: pipeline | agent"),
    llm_provider: str | None = typer.Option(None, "--llm-provider", help="覆盖默认 LLM Provider"),
    project: str | None = typer.Option(None, "--project", help="项目 ID"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="详细输出"),
) -> None:
    """对 ExecutionPackage 执行评估。"""
    from agent_eval.core.logging import setup_logging
    setup_logging(level="DEBUG" if verbose else "INFO")

    if eval_mode == "agent":
        rprint("[yellow]Agent 评估模式尚未实现，将在后续迭代中支持。[/yellow]")
        raise typer.Exit(code=1)

    rprint(f"[blue]评估模式:[/blue] {eval_mode}")
    rprint(f"[blue]执行包:[/blue] {package_dir}")
    rprint(f"[blue]规则集:[/blue] {rule_set}")

    # Sprint 5 完整实现
    rprint("[yellow]eval 命令的完整逻辑将在 Sprint 5 中实现。[/yellow]")


@app.command()
def run(
    task_set: str = typer.Option(..., "--task-set", help="任务集文件路径"),
    sut_config: str = typer.Option(..., "--sut-config", help="SUT 配置文件路径"),
    output_dir: str | None = typer.Option(None, "--output-dir", help="输出目录"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="详细输出"),
) -> None:
    """执行被测 Agent（ExecutionAgent 驱动），生成 ExecutionPackage。"""
    from agent_eval.core.logging import setup_logging
    setup_logging(level="DEBUG" if verbose else "INFO")

    rprint(f"[blue]任务集:[/blue] {task_set}")
    rprint(f"[blue]SUT 配置:[/blue] {sut_config}")

    # Sprint 8 完整实现
    rprint("[yellow]run 命令的完整逻辑将在 Sprint 8 中实现。[/yellow]")


@app.command()
def pipeline(
    task_set: str = typer.Option(..., "--task-set", help="任务集文件路径"),
    sut_config: str = typer.Option(..., "--sut-config", help="SUT 配置文件路径"),
    rule_set: str = typer.Option(..., "--rule-set", help="规则集文件路径"),
    eval_mode: str = typer.Option("pipeline", "--eval-mode", help="评估模式: pipeline | agent"),
    output_dir: str | None = typer.Option(None, "--output-dir", help="输出目录"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="详细输出"),
) -> None:
    """完整流水线：执行被测 Agent → 评估 → 生成报告。"""
    from agent_eval.core.logging import setup_logging
    setup_logging(level="DEBUG" if verbose else "INFO")

    rprint(f"[blue]任务集:[/blue] {task_set}")
    rprint(f"[blue]SUT 配置:[/blue] {sut_config}")
    rprint(f"[blue]规则集:[/blue] {rule_set}")
    rprint(f"[blue]评估模式:[/blue] {eval_mode}")

    # Sprint 9 完整实现
    rprint("[yellow]pipeline 命令的完整逻辑将在 Sprint 9 中实现。[/yellow]")


@app.command()
def serve(
    port: int = typer.Option(3000, "--port", "-p", help="Web Portal 端口"),
    host: str = typer.Option("localhost", "--host", help="监听地址"),
    workspace_dir: str = typer.Option("./workspace", "--workspace", help="Workspace 目录"),
) -> None:
    """启动 Web Portal。"""
    rprint(f"[blue]Web Portal:[/blue] http://{host}:{port}")
    rprint(f"[blue]Workspace:[/blue] {workspace_dir}")

    # Sprint 7a 完整实现
    rprint("[yellow]serve 命令将在 Sprint 7a 中实现。[/yellow]")


@app.command()
def index(
    workspace_dir: str = typer.Option("./workspace", "--workspace", help="Workspace 目录"),
) -> None:
    """重建 Workspace 索引（用于 Web Portal）。"""
    rprint(f"[blue]重建索引:[/blue] {workspace_dir}")

    # Sprint 7a 完整实现
    rprint("[yellow]index 命令将在 Sprint 7a 中实现。[/yellow]")


@app.command()
def version() -> None:
    """显示版本信息。"""
    from agent_eval import __version__
    rprint(f"agent-eval v{__version__}")


if __name__ == "__main__":
    app()
