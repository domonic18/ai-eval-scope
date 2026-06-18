"""CLI 入口 — typer 应用框架。

注册 eval、run、pipeline、serve、index 等子命令。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import typer
from dotenv import load_dotenv
from rich import print as rprint
from rich.table import Table

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


def _flush_observability(result: object, *, upload_override: bool | None) -> None:
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
        report = sink.flush(result, run_workspace=run_workspace)  # type: ignore[arg-type]
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
            rprint("[blue]模式:[/blue] 目录打包")
            rprint(f"[blue]源目录:[/blue] {source_dir}")
            builder.build_directory(
                task=task,
                source_dir=Path(source_dir),
                package_dir=pkg_dir,
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

        # 8. 推送到可观测平台（ResultSink，Sprint 7e）
        _flush_observability(result, upload_override=upload)

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
def serve(
    port: int = typer.Option(3000, "--port", "-p", help="Web Portal 端口"),
    host: str = typer.Option("localhost", "--host", help="监听地址"),
    workspace_dir: str = typer.Option("./workspace", "--workspace", help="Workspace 目录"),
) -> None:
    """启动 Web Portal。"""
    import os
    import subprocess

    from agent_eval.config.paths import PROJECT_ROOT

    workspace_path = Path(workspace_dir).resolve()
    backend_dir = PROJECT_ROOT / "web" / "backend"
    public_dir = backend_dir / "public"

    if not public_dir.exists() or not (public_dir / "index.html").exists():
        rprint(
            "[bold red]❌ 前端构建产物不存在。请先执行：[/bold red]\n"
            "  cd web/frontend && npm install && npm run build\n"
            "  cp -r web/frontend/dist/* web/backend/public/"
        )
        raise typer.Exit(code=1)

    env = os.environ.copy()
    env["WORKSPACE_DIR"] = str(workspace_path)
    env["PORT"] = str(port)
    env["HOST"] = host

    rprint(f"[blue]Web Portal:[/blue] http://{host}:{port}")
    rprint(f"[blue]Workspace:[/blue] {workspace_path}")

    try:
        subprocess.run(
            ["node", "server.js"],
            cwd=backend_dir,
            env=env,
            check=True,
        )
    except KeyboardInterrupt:
        rprint("\n[dim]Web Portal 已停止[/dim]")
    except FileNotFoundError:
        rprint("[bold red]❌ 未找到 Node.js，请安装 Node.js 以使用 Web Portal[/bold red]")
        raise typer.Exit(code=1) from None
    except subprocess.CalledProcessError as e:
        rprint(f"[bold red]❌ Web Portal 启动失败: {e}[/bold red]")
        raise typer.Exit(code=1) from e


@app.command()
def index(
    workspace_dir: str = typer.Option("./workspace", "--workspace", help="Workspace 目录"),
) -> None:
    """重建 Workspace 索引（用于 Web Portal）。"""
    from agent_eval.web.indexer import rebuild_index

    workspace_path = Path(workspace_dir).resolve()
    rprint(f"[blue]重建索引:[/blue] {workspace_path}")

    try:
        stats = rebuild_index(workspace_path)
        rprint("[green]✅ 索引重建完成[/green]")
        rprint(f"  项目数: {stats['project_count']}")
        rprint(f"  运行数: {stats['run_count']}")
    except Exception as e:
        rprint(f"[bold red]❌ 索引重建失败: {e}[/bold red]")
        raise typer.Exit(code=1) from e


@app.command()
def version() -> None:
    """显示版本信息。"""
    from agent_eval import __version__

    rprint(f"agent-eval v{__version__}")


# ─── Sprint 7: 规则集管理子命令 ───

rule_app = typer.Typer(name="rule-set", help="规则集管理：模板、版本、diff、回滚")
app.add_typer(rule_app)


def _print_rule_set_diff(diff: object) -> None:
    """Rich 打印 RuleSetDiff。"""
    from agent_eval.rules.models import RuleSetDiff

    if not isinstance(diff, RuleSetDiff):
        return

    rprint(
        f"\n[bold blue]═══ 规则集差异 ({diff.version_from} → {diff.version_to}) ═══[/bold blue]\n"
    )

    if diff.added_rules:
        rprint("[bold green]新增规则:[/bold green]")
        for r in diff.added_rules:
            rprint(f"  + {r.get('id')}: {r.get('name', '')}")
    if diff.removed_rules:
        rprint("\n[bold red]移除规则:[/bold red]")
        for r in diff.removed_rules:
            rprint(f"  - {r.get('id')}: {r.get('name', '')}")
    if diff.modified_rules:
        rprint("\n[bold yellow]修改规则:[/bold yellow]")
        for m in diff.modified_rules:
            rprint(f"  ~ {m.get('rule_id')}")
    if not diff.added_rules and not diff.removed_rules and not diff.modified_rules:
        rprint("[dim]无差异[/dim]")
    rprint("")


@rule_app.command("validate")
def rule_validate(
    rule_set_path: str = typer.Option(..., "--rule-set", "-r", help="规则集文件路径"),
    resolve_templates: bool = typer.Option(
        True, "--resolve-templates/--no-resolve", help="解析模板引用"
    ),
) -> None:
    """验证规则集语义正确性。"""
    from agent_eval.config.loader import ConfigLoader
    from agent_eval.rules.validation import RuleSetValidator

    try:
        rs = ConfigLoader.load_rule_set(
            rule_set_path,
            resolve_templates=resolve_templates,
        )
        errors = RuleSetValidator().validate(rs)
        if errors:
            rprint("[bold red]❌ 规则集语义校验失败:[/bold red]")
            for e in errors:
                rprint(f"  • [red]{e}[/red]")
            raise typer.Exit(code=1)
        rprint(f"[green]✅ 规则集校验通过: {rule_set_path}[/green]")
    except Exception as e:
        rprint(f"[bold red]❌ 校验失败: {e}[/bold red]")
        raise typer.Exit(code=1) from e


@rule_app.command("diff")
def rule_diff(
    rule_set_path: str = typer.Option(..., "--rule-set", "-r", help="规则集文件路径"),
    from_version: str | None = typer.Option(None, "--from", help="起始版本（默认当前磁盘版本）"),
    to_version: str | None = typer.Option(None, "--to", help="目标版本（默认最新归档版本）"),
) -> None:
    """显示规则集版本差异。"""
    from agent_eval.rules.manager import RuleSetManager

    try:
        manager = RuleSetManager(rule_set_path)
        diff = manager.diff(from_version, to_version)
        _print_rule_set_diff(diff)
    except Exception as e:
        rprint(f"[bold red]❌ diff 失败: {e}[/bold red]")
        raise typer.Exit(code=1) from e


@rule_app.command("apply")
def rule_apply(
    rule_set_path: str = typer.Option(..., "--rule-set", "-r", help="规则集文件路径"),
    message: str = typer.Option("", "--message", "-m", help="变更说明"),
) -> None:
    """应用规则集变更，自动归档旧版本。"""
    from agent_eval.config.loader import ConfigLoader
    from agent_eval.rules.manager import RuleSetManager

    try:
        rule_set = ConfigLoader.load_rule_set(rule_set_path, resolve_templates=False)
        manager = RuleSetManager(rule_set_path)
        version = manager.apply(rule_set, commit_message=message)
        rprint(f"[green]✅ 已应用规则集版本 {version}[/green]")
    except Exception as e:
        rprint(f"[bold red]❌ apply 失败: {e}[/bold red]")
        raise typer.Exit(code=1) from e


@rule_app.command("history")
def rule_history(
    rule_set_path: str = typer.Option(..., "--rule-set", "-r", help="规则集文件路径"),
    limit: int = typer.Option(10, "--limit", "-n", help="显示条数"),
) -> None:
    """显示规则集变更历史。"""
    from agent_eval.rules.manager import RuleSetManager

    try:
        manager = RuleSetManager(rule_set_path)
        changes = manager.list_history()
        if not changes:
            rprint("[dim]暂无变更历史[/dim]")
            return

        rprint("\n[bold blue]═══ 规则集变更历史 ═══[/bold blue]\n")
        for change in changes[-limit:]:
            rprint(
                f"  [{change.timestamp}] "
                f"[cyan]{change.version}[/cyan] "
                f"({change.change_type}): {change.description}"
            )
        rprint("")
    except Exception as e:
        rprint(f"[bold red]❌ history 失败: {e}[/bold red]")
        raise typer.Exit(code=1) from e


@rule_app.command("rollback")
def rule_rollback(
    rule_set_path: str = typer.Option(..., "--rule-set", "-r", help="规则集文件路径"),
    version: str | None = typer.Option(
        None, "--version", "-v", help="回滚目标版本（默认最近归档）"
    ),
) -> None:
    """回滚到指定版本。"""
    from agent_eval.rules.manager import RuleSetManager

    try:
        manager = RuleSetManager(rule_set_path)
        rs = manager.rollback(version)
        rprint(f"[green]✅ 已回滚到规则集版本 {rs.version}[/green]")
    except Exception as e:
        rprint(f"[bold red]❌ rollback 失败: {e}[/bold red]")
        raise typer.Exit(code=1) from e


@rule_app.command("list-templates")
def rule_list_templates(
    rule_set_path: str = typer.Option(..., "--rule-set", "-r", help="规则集文件路径"),
) -> None:
    """列出规则集中定义的模板。"""
    from agent_eval.config.loader import ConfigLoader

    try:
        rs = ConfigLoader.load_rule_set(rule_set_path, resolve_templates=False)
        if not rs.templates:
            rprint("[dim]本规则集未定义模板[/dim]")
            return

        rprint("\n[bold blue]═══ 规则模板 ═══[/bold blue]\n")
        for t in rs.templates:
            rprint(f"  • [cyan]{t.id}[/cyan]: {t.name} ({t.evaluator})")
        rprint("")
    except Exception as e:
        rprint(f"[bold red]❌ list-templates 失败: {e}[/bold red]")
        raise typer.Exit(code=1) from e


if __name__ == "__main__":
    app()
