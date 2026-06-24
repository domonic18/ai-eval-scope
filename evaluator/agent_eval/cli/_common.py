"""CLI 共享辅助 — Rich 输出、LLM Judge 初始化、结果摘要、可观测推送。

各顶层命令与子命令组共同使用的工具函数集中于此，保持命令体聚焦业务逻辑。
"""

from __future__ import annotations

import typer
from rich import print as rprint
from rich.table import Table

__all__ = [
    "Table",
    "rprint",
    "_check_llm_availability",
    "_flush_observability",
    "_init_judge_orchestrator",
    "_print_summary",
]


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


def _check_llm_availability(
    rule_set_obj: object, judge_orch: object | None, require_llm: bool
) -> None:
    """预检：rule_set 含 LLM 评估器但 Judge 未配置时提示/阻断。

    LLM 评估器：soft.*/pref.* 与 commonsense.logical_consistency。

    - 默认（require_llm=False）：警告列出将跳过的评估器，继续执行（降级为 SKIP，不计分）
    - require_llm=True：阻断退出，提示用户先配置 LLM
    """
    llm_prefixes = ("soft.", "pref.")
    llm_exact = {"commonsense.logical_consistency"}
    llm_evaluators = [
        r.evaluator  # type: ignore[attr-defined]
        for r in rule_set_obj.rules  # type: ignore[attr-defined]
        if getattr(r, "enabled", True)
        and (r.evaluator.startswith(llm_prefixes) or r.evaluator in llm_exact)  # type: ignore[attr-defined]
    ]
    if not llm_evaluators or judge_orch is not None:
        return

    rprint("[yellow]⚠ 以下评估器依赖 LLM 但 Judge 未配置，将跳过（不计入得分）：[/yellow]")
    rprint(f"[yellow]   {', '.join(llm_evaluators)}[/yellow]")
    rprint("[yellow]   请通过 --llm-config 配置 LLM 后重试。[/yellow]")
    if require_llm:
        raise typer.Exit(code=1)


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

    if getattr(result, "llm_skipped", 0):
        rprint(
            f"[yellow]⚠ LLM 不可用：{result.llm_skipped} 项评估已跳过（不计入得分）[/yellow]"
        )

    rprint("")


def _flush_observability(
    result: object, *, upload_override: bool | None, package_dir: str | None = None
) -> None:
    """评估完成后把结果推送到可观测平台（ResultSink，Sprint 7e）。

    未配置凭据（enabled=False）→ 静默跳过。失败不阻断 eval 命令（已落本地 workspace + 入离线队列）。
    """
    from agent_eval.observability import ResultSink, load_config

    cfg = load_config(upload_override=upload_override)
    if not cfg.enabled:
        return

    rprint("[blue]可观测平台:[/blue] 推送结果中…")
    run_workspace = None
    rw = getattr(result, "run_workspace", None)
    if rw is not None:
        run_workspace = getattr(rw, "root", None) or (rw.path if hasattr(rw, "path") else None)

    try:
        sink = ResultSink(cfg)
        report = sink.flush(
            result,  # type: ignore[arg-type]
            run_workspace=run_workspace,
            package_dir=package_dir,
        )
        if report.error:
            rprint(f"[yellow]⚠ 推送异常（已入离线队列，后续自动重放）: {report.error}[/yellow]")
        else:
            rprint(
                f"[green]✓ 已推送[/green] 事件 {report.sent}、入队 {report.queued}、"
                f"制品 {report.artifacts_uploaded}/{report.artifacts_uploaded + report.artifacts_failed}、"
                f"重放 {report.replayed}"
            )
    except Exception as exc:  # noqa: BLE001 — 推送失败不影响评估结论
        rprint(f"[yellow]⚠ 可观测平台推送初始化失败（结果仍在本地 workspace）: {exc}[/yellow]")
