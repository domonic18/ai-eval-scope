"""CLI 入口 — typer 应用框架。

注册 eval、run、pipeline、serve、index 等子命令。
"""

from __future__ import annotations

from pathlib import Path

import typer
from rich import print as rprint
from rich.table import Table

app = typer.Typer(
    name="agent-eval",
    help="Agent 能力评估系统 — 基于 Agent-Driven 架构的评测框架",
    no_args_is_help=True,
)


def _init_judge_orchestrator(
    llm_config_path: str | None,
    llm_provider: str | None,
) -> object | None:
    """初始化 JudgeOrchestrator（可选）。"""
    if llm_config_path is None:
        return None

    try:
        from agent_eval.config.loader import ConfigLoader
        from agent_eval.llm.judge.orchestrator import JudgeOrchestrator
        from agent_eval.llm.judge.stability import StabilityController
        from agent_eval.llm.judge.structured_output import StructuredOutputParser
        from agent_eval.llm.judge.template_manager import TemplateManager
        from agent_eval.llm.pool import ProviderPool

        llm_config = ConfigLoader.load_llm_config(llm_config_path)
        pool = ProviderPool(llm_config)
        template_dir = Path(__file__).parent / "assets" / "prompts"
        templates = TemplateManager(template_dir)
        templates.load_all()
        stability = StabilityController()
        parser = StructuredOutputParser()

        return JudgeOrchestrator(
            pool=pool,
            template_manager=templates,
            stability=stability,
            parser=parser,
        )
    except Exception as e:
        rprint(f"[yellow]⚠ LLM Judge 初始化失败，LLM 评估器将降级: {e}[/yellow]")
        return None


def _print_summary(result: object) -> None:
    """Rich 格式化输出评估摘要到终端。"""
    from agent_eval.evaluation.models import MetricsReport

    if not isinstance(result, MetricsReport):
        return

    rprint("")
    rprint("[bold blue]═══ 评估结果摘要 ═══[/bold blue]")
    rprint(f"  运行 ID: [cyan]{result.run_id}[/cyan]")
    rprint(f"  样本总数: {result.total_samples}")
    rprint("")

    table = Table(title="指标概览")
    table.add_column("指标", style="bold")
    table.add_column("值", justify="right")
    table.add_column("状态")

    dr_status = "✅" if result.dr >= 0.95 else "❌"
    cpr_status = "✅" if result.cpr >= 0.90 else "❌"
    reward_status = "✅" if result.avg_reward >= 0.70 else "❌"

    table.add_row("DR (交付率)", f"{result.dr:.3f}", dr_status)
    table.add_row("CPR (约束通过率)", f"{result.cpr:.3f}", cpr_status)
    table.add_row("Avg Reward", f"{result.avg_reward:.3f}", reward_status)
    table.add_row("CondR (条件Reward)", f"{result.cond_r:.3f}", "—")
    table.add_row("Avg Time", f"{result.avg_time_ms:.0f}ms", "—")

    rprint(table)

    if result.failure_breakdown:
        rprint("")
        rprint("[bold red]失败项:[/bold red]")
        for cid, count in sorted(
            result.failure_breakdown.items(), key=lambda x: x[1], reverse=True
        ):
            rprint(f"  • [red]{cid}[/red]: {count} 次")

    rprint("")


@app.command()
def eval(
    package_dir: str = typer.Option(..., "--package-dir", help="ExecutionPackage 目录路径"),
    rule_set: str = typer.Option(..., "--rule-set", help="规则集文件路径"),
    output_dir: str | None = typer.Option(None, "--output-dir", help="输出目录"),
    eval_mode: str = typer.Option("pipeline", "--eval-mode", help="评估模式: pipeline | agent"),
    llm_provider: str | None = typer.Option(None, "--llm-provider", help="覆盖默认 LLM Provider"),
    llm_config: str | None = typer.Option(None, "--llm-config", help="LLM 配置文件路径"),
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

    try:
        from agent_eval.config.loader import ConfigLoader
        from agent_eval.orchestrator.orchestrator import Orchestrator
        from agent_eval.storage.workspace import Workspace

        # 1. 加载 RuleSet
        rule_set_obj = ConfigLoader.load_rule_set(rule_set)

        # 2. 初始化 LLM Judge（可选）
        judge_orch = _init_judge_orchestrator(llm_config, llm_provider)

        # 3. 创建 Workspace
        ws = Workspace(output_dir) if output_dir else Workspace()

        # 4. 创建 Orchestrator 并执行
        orch = Orchestrator(workspace=ws)
        result = orch.eval_only(
            Path(package_dir),
            rule_set_obj,
            judge_orchestrator=judge_orch,
            llm_provider=llm_provider,
            project=project,
        )

        # 5. 输出摘要
        _print_summary(result.report)

        rprint("[green]✅ 评估完成[/green] — 结果已保存至 workspace")

    except Exception as e:
        rprint(f"[bold red]❌ 评估失败: {e}[/bold red]")
        raise typer.Exit(code=1) from e


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
