"""CLI 顶层命令 — pack / eval / run / pipeline / upload / version。

子命令组（rule-set / dataset / knowledge）在各自模块，由 ``agent_eval.cli`` 包组装挂载。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import typer
from dotenv import load_dotenv

from agent_eval.cli._common import (
    _check_llm_availability,
    _flush_observability,
    _init_judge_orchestrator,
    _print_summary,
    rprint,
)

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


def _content_hash(source_dir: Path) -> str | None:
    """计算目录内容的稳定短哈希（SHA256 前 8 位），用于样本内容寻址（docs/arch/13 §5）。

    按「相对路径 + 文件内容」聚合哈希（相对路径排序保证遍历顺序稳定），
    确保同内容同哈希、不同内容不同哈希，不受时间戳/路径位置/遍历顺序影响。
    隐藏文件（.DS_Store 等）排除以提升稳定性。空目录返回 None（调用方回退到目录名）。
    """
    import hashlib

    h = hashlib.sha256()
    files = sorted(
        p
        for p in source_dir.rglob("*")
        if p.is_file() and not any(part.startswith(".") for part in p.relative_to(source_dir).parts)
    )
    if not files:
        return None
    for p in files:
        h.update(p.relative_to(source_dir).as_posix().encode("utf-8"))
        h.update(b"\x00")
        h.update(p.read_bytes())
        h.update(b"\x00")
    return h.hexdigest()[:8]


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

        # 自动推导 task_id：取末级目录名作为「逻辑课件标识」（跨版本稳定，便于走势聚合）。
        # 内容指纹另存为 content_hash 字段（溯源/版本标记），不混入 task_id。
        # 不同课件若同名，应以 --task-id 显式区分（详见 docs/arch/13 §5）。
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
            rprint("[blue]模式:[/blue] 目录打包")
            rprint(f"[blue]源目录:[/blue] {source_dir}")
            content_hash = _content_hash(Path(source_dir))
            builder.build_directory(
                task=task,
                source_dir=Path(source_dir),
                package_dir=pkg_dir,
                content_hash=content_hash,
            )
        else:
            rprint("[blue]模式:[/blue] 文件打包")
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
    upload: bool | None = typer.Option(
        None,
        "--upload/--no-upload",
        help="评估完成后把结果推送到可观测平台（覆盖 AGENT_EVAL_UPLOAD）",
    ),
    require_llm: bool = typer.Option(
        False, "--require-llm", help="要求 LLM 可用（质量/偏好评估依赖）；不可用时阻断退出"
    ),
    no_cache: bool = typer.Option(
        False, "--no-cache", help="跳过评估缓存，强制重新评估（含 LLM 调用）"
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
        #    --llm-config 未指定时，按优先级查找：
        #    a) CWD/llm_config.yaml（用户当前目录，pip install 场景）
        #    b) 包内 assets/configs/llm_config.yaml（开发库内置，dev 场景）
        if llm_config is None:
            from pathlib import Path as _Path

            from agent_eval.config.paths import paths

            cwd_cfg = _Path.cwd() / "llm_config.yaml"
            pkg_cfg = paths.configs_dir / "llm_config.yaml"
            if cwd_cfg.exists():
                llm_config = str(cwd_cfg)
            elif pkg_cfg.exists():
                llm_config = str(pkg_cfg)
        judge_orch = _init_judge_orchestrator(llm_config, llm_provider)

        # 构造 LLM 指纹（纳入 cache_key，LLM 配置/可用性变更时缓存自动失效）
        import hashlib

        if judge_orch is not None and llm_config:
            llm_signature = hashlib.sha256(Path(llm_config).read_bytes()).hexdigest()[:12]
        else:
            llm_signature = "no-llm"

        # LLM 可用性预检：rule_set 含 LLM 评估器但 Judge 未配置时提示/阻断
        _check_llm_availability(rule_set_obj, judge_orch, require_llm)

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
                llm_signature=llm_signature,
                no_cache=no_cache,
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

        # 8. 推送到可观测平台（ResultSink，Sprint 7e）
        _flush_observability(result, upload_override=upload, package_dir=package_dir)

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
def upload(
    run: str = typer.Option(..., "--run", help="要回填的运行 ID（workspace/runs/{run}）"),
    workspace: str = typer.Option("./workspace", "--workspace", help="Workspace 目录"),
    project: str | None = typer.Option(
        None, "--project", help="目标项目（覆盖 AGENT_EVAL_PROJECT）"
    ),
) -> None:
    """把历史运行的评估结果回填到可观测平台（Sprint 7e）。

    从 workspace/runs/{run}/ 的 summary.json + 各 task 的 report.json 重建事件并推送。
    需配置 AGENT_EVAL_HOST / AGENT_EVAL_PUBLIC_KEY / AGENT_EVAL_SECRET_KEY。
    """
    import json as _json

    from agent_eval.evaluation.models import SampleResult
    from agent_eval.observability import ResultSink, load_config
    from agent_eval.observability.events import (
        build_constraint_event,
        build_sample_event,
    )

    run_dir = Path(workspace).resolve() / "runs" / run
    if not run_dir.exists():
        rprint(f"[red]运行目录不存在: {run_dir}[/red]")
        raise typer.Exit(code=1)

    summary_path = run_dir / "reports" / "summary.json"
    if not summary_path.exists():
        rprint(f"[red]缺少 summary.json: {summary_path}[/red]")
        raise typer.Exit(code=1)
    summary = _json.loads(summary_path.read_text(encoding="utf-8"))

    env_override: dict[str, str] = {}
    if project:
        env_override["AGENT_EVAL_PROJECT"] = project
    # upload 子命令默认强制开启上传
    cfg = load_config(upload_override=True)
    if not cfg.has_credentials():
        rprint(
            "[red]未配置凭据：请设置 AGENT_EVAL_HOST / AGENT_EVAL_PUBLIC_KEY / AGENT_EVAL_SECRET_KEY[/red]"
        )
        raise typer.Exit(code=1)

    metrics = summary.get("metrics", {})
    events: list[dict[str, Any]] = [
        {
            "event_id": __import__("uuid").uuid4().hex,
            "type": "run",
            "data": {
                "external_run_id": summary.get("run_id", run),
                "mode": "eval_only",
                "status": "completed",
                "metrics": {
                    "DR": metrics.get("DR", 0.0),
                    "CPR": metrics.get("CPR", 0.0),
                    "avg_reward": metrics.get("avg_reward", 0.0),
                    "condR": metrics.get("condR", 0.0),
                    "avg_time_ms": metrics.get("avg_time_ms", 0.0),
                },
                "total_samples": summary.get("total_samples", 0),
                "rule_set_version": summary.get("rule_set_version"),
                "failure_breakdown": summary.get("failure_breakdown") or None,
                "thresholds": summary.get("thresholds") or None,
            },
        }
    ]

    results_dir = run_dir / "results"
    sample_count = 0
    if results_dir.exists():
        for task_dir in sorted(p for p in results_dir.iterdir() if p.is_dir()):
            report_path = task_dir / "report.json"
            if not report_path.exists():
                continue
            try:
                sample = SampleResult.from_dict(
                    _json.loads(report_path.read_text(encoding="utf-8"))
                )
            except Exception as exc:  # noqa: BLE001
                rprint(f"[yellow]跳过 {task_dir.name}: 解析失败 {exc}[/yellow]")
                continue
            events.append(build_sample_event(sample, external_run_id=summary.get("run_id", run)))
            for stage in sample.stage_results.values():
                for c in stage.constraint_results:
                    events.append(
                        build_constraint_event(
                            c,
                            external_run_id=summary.get("run_id", run),
                            external_sample_id=sample.sample_id,
                        )
                    )
            sample_count += 1

    rprint(f"[blue]回填:[/blue] 运行 {run}，样本 {sample_count}，事件 {len(events)}")
    sink = ResultSink(cfg)
    sent, queued = sink.dispatch(events)
    rprint(f"[green]✓ 回填完成[/green] 已发送 {sent}、入队 {queued}")


@app.command()
def version() -> None:
    """显示版本信息。"""
    from agent_eval import __version__

    rprint(f"agent-eval v{__version__}")


if __name__ == "__main__":
    app()
