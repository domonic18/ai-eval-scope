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
    "observability_enabled",
    "observability_flush",
    "rprint",
    "_check_llm_availability",
    "_flush_observability",
    "_init_judge_orchestrator",
    "_print_summary",
    "_render_upload_receipt",
]


# ── 执行前凭证保障（按所选 SUT 的 credential_ref 引导补齐缺失字段）──


def ensure_sut_credentials(sut: Any) -> None:
    """执行前凭证保障（run/pipeline/suite 在**进度视图启动前**调用）：

    缺失时交互补录，复检仍缺则 fail fast。交互终端：列出缺失字段 → 确认后
    逐项隐藏输入 → **一次落盘**（不留半截状态）→ 复检通过；取消 / 空输入退回
    预检原样抛 SUTAuthError（带 ``secrets set`` 引导）。``--no-input``（CI /
    管道）不交互，行为与纯预检完全一致。字段集由 sut_config 数据推导。
    **不得移进 stage_progress 内调用**——进度转轮单行
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


def _run_workspace_of(result: object) -> Any:
    """从 EvalResult 提取 run workspace 根（observability 队列目录锚点）。"""
    rw = getattr(result, "run_workspace", None)
    if rw is not None:
        return getattr(rw, "root", None) or (rw.path if hasattr(rw, "path") else None)
    return None


def observability_enabled(result: object, *, upload_override: bool | None) -> bool:
    """是否启用平台上报（load_config 仅读 env，重复调用无害）。"""
    from agent_eval.observability import load_config

    # 队列目录必须随 run workspace：config 的回退是 CWD 相对路径（.ingest_queue），
    # 而容器里 CWD 常是只读的场景包挂载（:ro）——创建即炸会吞掉整个推送，
    # 且表现为「构建绿但平台无数据」（构建 #10-#18 实录）。先取 workspace 再建配置。
    cfg = load_config(workspace=_run_workspace_of(result), upload_override=upload_override)
    return bool(cfg.enabled)


def observability_flush(
    result: object, *, upload_override: bool | None, package_dir: str | None = None
) -> dict:
    """把结果推送到可观测平台（无渲染核心，workbench/管线共用）。

    回执（异常全吞——推送失败不阻断评估结论，已落本地 workspace + 入离线队列）::

        {"enabled", "init_error", "error", "sent", "queued",
         "artifacts_uploaded", "artifacts_failed", "replayed", "view_url"}

    ``enabled=False``（未配置凭据）时计数键为缺省 0。``view_url`` 查看页地址
    确定性拼装（/run/:id），不依赖推送成败，离线重放成功后同样有效。
    """
    from agent_eval.observability import ResultSink, load_config

    receipt: dict = {
        "enabled": False,
        "init_error": "",
        "error": "",
        "sent": 0,
        "queued": 0,
        "artifacts_uploaded": 0,
        "artifacts_failed": 0,
        "replayed": 0,
        "view_url": "",
    }
    cfg = load_config(workspace=_run_workspace_of(result), upload_override=upload_override)
    if not cfg.enabled:
        return receipt
    receipt["enabled"] = True
    receipt["view_url"] = cfg.run_view_url(str(getattr(result, "run_id", "") or ""))

    try:
        sink = ResultSink(cfg)
        report = sink.flush(
            result,  # type: ignore[arg-type]
            run_workspace=_run_workspace_of(result),
            package_dir=package_dir,
        )
        if report.error:
            receipt["error"] = str(report.error)
        else:
            receipt.update(
                sent=report.sent,
                queued=report.queued,
                artifacts_uploaded=report.artifacts_uploaded,
                artifacts_failed=report.artifacts_failed,
                replayed=report.replayed,
            )
    except Exception as exc:  # noqa: BLE001 — 推送失败不影响评估结论
        receipt["init_error"] = str(exc)
    return receipt


def _render_upload_receipt(receipt: dict) -> None:
    """按回执渲染上报结果（不含「推送结果中…」横幅——横幅由调用方先行打印）。

    文案与拆分前逐字一致：推送异常 / 已推送明细 / 平台报告 / 初始化失败四分支。
    """
    if not receipt.get("enabled"):
        return
    view_url = receipt.get("view_url", "")
    if receipt.get("init_error"):
        rprint(
            f"[yellow]⚠ 可观测平台推送初始化失败（结果仍在本地 workspace）: "
            f"{receipt['init_error']}[/yellow]"
        )
    elif receipt.get("error"):
        rprint(f"[yellow]⚠ 推送异常（已入离线队列，后续自动重放）: {receipt['error']}[/yellow]")
        if view_url:
            rprint(f"[yellow]平台报告（重放成功后可访问）: {view_url}[/yellow]")
    else:
        up, failed = receipt["artifacts_uploaded"], receipt["artifacts_failed"]
        rprint(
            f"[green]✓ 已推送[/green] 事件 {receipt['sent']}、入队 {receipt['queued']}、"
            f"制品 {up}/{up + failed}、重放 {receipt['replayed']}"
        )
        if view_url:
            rprint(f"[green]平台报告: {view_url}[/green]")


def _flush_observability(
    result: object, *, upload_override: bool | None, package_dir: str | None = None
) -> None:
    """评估完成后把结果推送到可观测平台（组合壳；签名与行为不变，eval/suite 路径零改动）。

    未配置凭据（enabled=False）→ 静默跳过。失败不阻断 eval 命令（已落本地 workspace + 入离线队列）。
    """
    if observability_enabled(result, upload_override=upload_override):
        rprint("[blue]可观测平台:[/blue] 推送结果中…")
    _render_upload_receipt(
        observability_flush(result, upload_override=upload_override, package_dir=package_dir)
    )
