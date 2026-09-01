"""CLI 共享辅助 — Rich 输出、LLM Judge 初始化、结果摘要、可观测推送。

各顶层命令与子命令组共同使用的工具函数集中于此，保持命令体聚焦业务逻辑。
"""

from __future__ import annotations

from typing import Any

import typer
from rich import print as rprint
from rich.table import Table

__all__ = [
    "Table",
    "ensure_sut_credentials",
    "rprint",
    "_check_llm_availability",
    "_flush_observability",
    "_init_judge_orchestrator",
    "_print_summary",
]


# ── 执行前凭证保障（req/04 §3.5：按所选 SUT 的 credential_ref 引导补齐缺失字段）──


def ensure_sut_credentials(sut: Any) -> None:
    """执行前凭证保障（run/pipeline/suite 在**进度视图启动前**调用）：

    缺失时交互补录，复检仍缺则 fail fast。交互终端：列出缺失字段 → 确认后
    逐项隐藏输入 → **一次落盘**（不留半截状态）→ 复检通过；取消 / 空输入退回
    预检原样抛 SUTAuthError（带 ``secrets set`` 引导）。``--no-input``（CI /
    管道）不交互，行为与纯预检完全一致。字段集由 sut_config 数据推导
    （06 §4.7 通用 KV）。**不得移进 stage_progress 内调用**——进度转轮单行
    重绘会把输入提示行刷掉（实测：提示被「执行 N 个任务」掩盖，用户不知所措）。
    """
    import os

    from agent_eval.execution.auth.credentials import (
        missing_credential_fields,
        preflight_sut_credentials,
    )

    missing = missing_credential_fields(sut)
    if missing and not os.environ.get("AGENT_EVAL_NO_INPUT"):
        _fill_missing_credentials(sut, missing)  # 取消/失败不在此抛，交由复检
    preflight_sut_credentials(sut)  # 复检：仍缺（含 ref 缺失等配置错误）即原样 fail fast


def _fill_missing_credentials(sut: Any, missing: list[str]) -> None:
    """交互补录 sut 缺失凭证字段（隐藏输入，一次落盘；任一空输入整体取消）。"""
    from agent_eval.cli.console.prompts import ask, confirm
    from agent_eval.execution.auth.secrets_store import load_secrets_file, save_secrets_file

    ref = str(getattr(getattr(sut, "auth", None), "credential_ref", ""))
    keys = ", ".join(f"{ref}.{field}" for field in missing)
    rprint(f"[yellow]⚠ SUT {sut.name} 缺少凭证: {keys}（sut_config 声明）[/yellow]")
    if not confirm("现在录入？（隐藏输入，保存到本机密钥区 0600）", default=True):
        return
    values: dict[str, str] = {}
    for field in missing:
        value = ask(f"{ref}.{field}", hide=True)
        if not value:
            rprint(f"[yellow]未输入 {ref}.{field}，已取消补录。[/yellow]")
            return
        values[field] = value
    secrets = load_secrets_file()
    secrets.setdefault(ref, {}).update(values)
    path = save_secrets_file(secrets)
    rprint(f"[green]✅ 已保存[/green] {keys} → {path}（0600）")


def _init_judge_orchestrator(
    llm_config: object | None,
    prompts_dir: str | None = None,
) -> object | None:
    """初始化 JudgeOrchestrator（可选；llm_config 为已解析的 LLMConfig 实例）。"""
    if llm_config is None:
        return None

    try:
        from pathlib import Path

        from agent_eval.llm.judge.file_prompt_store import FilePromptStore
        from agent_eval.llm.judge.orchestrator import JudgeOrchestrator
        from agent_eval.llm.judge.stability import StabilityController
        from agent_eval.llm.judge.structured_output import StructuredOutputParser
        from agent_eval.llm.pool import ProviderPool

        pool = ProviderPool(llm_config)  # type: ignore[arg-type]
        from agent_eval.config.paths import paths

        # 优先用场景包的 prompts/（code→code_correctness），缺省回退内置 courseware prompts
        _prompts = (
            Path(prompts_dir) if prompts_dir and Path(prompts_dir).exists() else paths.prompts_dir
        )
        templates = FilePromptStore(_prompts)
        templates.load_all()
        stability = StabilityController()
        parser = StructuredOutputParser()

        return JudgeOrchestrator(
            pool=pool,
            prompt_store=templates,
            stability=stability,
            parser=parser,
        )
    except Exception as e:
        rprint(f"[yellow]⚠ LLM Judge 初始化失败，LLM 评估器将降级: {e}[/yellow]")
        return None


def _check_llm_availability(rule_set_obj: object, judge_orch: object | None, strict: bool) -> None:
    """预检：rule_set 含需 LLM 的评估器但 Judge 未配置时提示/阻断。

    能力需求由 CapabilityResolver 从规则集派生（评估器自描述），不再用字符串前缀猜测。

    - strict=False（默认，--on-missing-capability=skip）：警告列出将跳过的评估器，继续
    - strict=True（--on-missing-capability=strict）：阻断退出，提示用户先配置 LLM
    """
    from agent_eval.core.types import Capability
    from agent_eval.evaluation.capability import CapabilityResolver
    from agent_eval.evaluation.registry import registry

    required = CapabilityResolver(registry).resolve(rule_set_obj)
    llm_evaluators = sorted(
        eid for eid, caps in required.by_evaluator.items() if Capability.LLM in caps
    )
    if not llm_evaluators or judge_orch is not None:
        return

    rprint("[yellow]⚠ 以下评估器依赖 LLM 但 Judge 未配置，将跳过（不计入得分）：[/yellow]")
    rprint(f"[yellow]   {', '.join(llm_evaluators)}[/yellow]")
    rprint("[yellow]   运行 agent-eval models set 配置 LLM 后重试。[/yellow]")
    if strict:
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

    # 场景化指标：从 metrics dict + metric_definitions 动态渲染（去 DR/CPR 硬编码）
    metrics_by_id = result.metrics
    for md in result.metric_definitions:
        mid = md.get("id")
        if mid is None or mid not in metrics_by_id:
            continue
        name = md.get("name") or mid
        value = metrics_by_id[mid]
        threshold = md.get("threshold")
        if threshold is not None:
            status = "✅" if value >= threshold else "❌"
            table.add_row(name, f"{value:.3f}", status)
        else:
            table.add_row(name, f"{value:.3f}", "—")
    # 兜底：metric_definitions 未覆盖的残余指标
    rendered_ids = {md.get("id") for md in result.metric_definitions}
    for mid, value in metrics_by_id.items():
        if mid not in rendered_ids:
            table.add_row(mid, f"{value:.3f}", "—")
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
        rprint(f"[yellow]⚠ LLM 不可用：{result.llm_skipped} 项评估已跳过（不计入得分）[/yellow]")

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
