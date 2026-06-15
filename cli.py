"""CLI 入口 — typer 应用框架。

注册 eval、run、pipeline、serve、index 等子命令。
"""

from __future__ import annotations

from pathlib import Path

import typer
from dotenv import load_dotenv
from rich import print as rprint
from rich.table import Table

# 在任何配置解析之前加载 .env
load_dotenv()

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
        from agent_eval.config.paths import paths

        templates = TemplateManager(paths.prompts_dir)
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

        # 自动推导 task_id
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
            rprint(f"[blue]模式:[/blue] 目录打包")
            rprint(f"[blue]源目录:[/blue] {source_dir}")
            builder.build_directory(
                task=task,
                source_dir=Path(source_dir),
                package_dir=pkg_dir,
            )
        else:
            rprint(f"[blue]模式:[/blue] 文件打包")
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


@app.command()
def eval(
    package_dir: str = typer.Option(..., "--package-dir", help="ExecutionPackage 目录路径"),
    rule_set: str = typer.Option(..., "--rule-set", help="规则集文件路径"),
    output_dir: str | None = typer.Option(None, "--output-dir", help="输出目录"),
    eval_mode: str = typer.Option("pipeline", "--eval-mode", help="评估模式: pipeline | agent"),
    llm_provider: str | None = typer.Option(None, "--llm-provider", help="覆盖默认 LLM Provider"),
    llm_config: str | None = typer.Option(None, "--llm-config", help="LLM 配置文件路径"),
    project: str | None = typer.Option(None, "--project", help="项目 ID"),
    enable_vision: bool = typer.Option(
        False, "--enable-vision", help="启用多模态视觉评估（需安装 vision extra 与视觉 Provider）"
    ),
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
    if enable_vision:
        rprint("[blue]视觉评估:[/blue] 已启用")

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

        # 4. 创建截图渲染器（仅 --enable-vision 时）
        renderer = None
        if enable_vision:
            try:
                from agent_eval.evaluation.vision import PlaywrightScreenshotRenderer

                renderer = PlaywrightScreenshotRenderer()
            except Exception as e:
                rprint(f"[yellow]⚠ 视觉渲染器初始化失败，视觉评估器将降级: {e}[/yellow]")

        # 5. 创建 Orchestrator 并执行
        orch = Orchestrator(workspace=ws)
        try:
            result = orch.eval_only(
                Path(package_dir),
                rule_set_obj,
                judge_orchestrator=judge_orch,
                llm_provider=llm_provider,
                project=project,
                with_vision=enable_vision,
                screenshot_renderer=renderer,
            )
        finally:
            if renderer is not None:
                renderer.close()

        # 6. 刷新 Langfuse trace 数据
        from agent_eval.llm.tracing import flush_traces

        flush_traces()

        # 7. 输出摘要
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
