"""CLI 顶层命令 — pack / eval / run / pipeline / upload / version。

子命令组（rule-set / dataset / knowledge）在各自模块，由 ``agent_eval.cli`` 包组装挂载。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

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

# 子命令组：模型配置管理（arch/16 §6.2-四 CLI 形态）
from agent_eval.cli.models import models_app  # noqa: E402
from agent_eval.cli.secrets import secrets_app  # noqa: E402
from agent_eval.cli.suite import suite_app  # noqa: E402

app.add_typer(models_app, name="models")
app.add_typer(secrets_app, name="secrets")
app.add_typer(suite_app, name="suite")


def _content_hash(source_dir: Path) -> str | None:
    """计算目录内容的稳定短哈希（SHA256 前 8 位），用于样本内容寻址。

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
        # 不同课件若同名，应以 --task-id 显式区分。
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


def _write_run_manifest(run_dir: Path, payload: dict[str, Any]) -> None:
    """写运行清单（委托 _stages.write_run_manifest，保留旧名供既有引用）。"""
    from agent_eval.cli._stages import write_run_manifest

    write_run_manifest(run_dir, payload)


def _detect_run_mode(package_dir: Path) -> str:
    """从包目录推断运行模式上报值（run 产物 → agent，pipeline 产物 → pipeline）。

    ``agent-eval run`` 会在 runs/{run_id}/ 写 run_manifest.json（mode=run）、
    pipeline 写 mode=pipeline；eval 的包目录位于其 packages/（或 packages/{task}）
    下时，向上找清单按原语义上报，避免平台误显示「仅评估」。
    """
    import json

    for ancestor in (package_dir.parent, package_dir.parent.parent):
        manifest = ancestor / "run_manifest.json"
        if manifest.is_file():
            try:
                mode = json.loads(manifest.read_text(encoding="utf-8")).get("mode")
                if mode == "run":
                    return "agent"
                if mode == "pipeline":
                    return "pipeline"
            except (OSError, ValueError):
                pass
            break
    return "eval_only"


@app.command()
def eval(
    package_dir: str = typer.Option(..., "--package-dir", help="ExecutionPackage 目录路径"),
    rule_set: str | None = typer.Option(
        None, "--rule-set", help="规则集：包内名称（与 --package 配合）或文件路径"
    ),
    package: str | None = typer.Option(
        None,
        "--package",
        help="ScenarioPackage 引用（如 courseware 或 courseware:production）；解析后从包内 rules/ 取规则集",
    ),
    output_dir: str | None = typer.Option(None, "--output-dir", help="输出目录"),
    eval_mode: str = typer.Option("pipeline", "--eval-mode", help="评估模式: pipeline | agent"),
    project: str | None = typer.Option(None, "--project", help="项目 ID"),
    upload: bool | None = typer.Option(
        None,
        "--upload/--no-upload",
        help="评估完成后把结果推送到可观测平台（覆盖 AGENT_EVAL_UPLOAD）",
    ),
    on_missing: str = typer.Option(
        "skip",
        "--on-missing-capability",
        help="所需能力不可用时：strict=阻断退出（推荐），skip=降级跳过并继续（默认）",
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
    strict = on_missing == "strict"

    try:
        from agent_eval.cli._stages import (
            build_judge_context,
            evaluate_stage,
            finalize_eval,
            resolve_eval_inputs,
        )

        # 0. 解析规则集路径：--package（ScenarioPackage 解析）或 --rule-set（路径/包内名）
        rule_set_path = resolve_eval_inputs(package, rule_set)
        rprint(f"[blue]规则集:[/blue] {rule_set_path}" + (f"（包: {package}）" if package else ""))

        # 1-4. RuleSet 加载 + LLM/Judge + 能力/视觉派生（共享段）
        judge_ctx = build_judge_context(rule_set_path, strict=strict)

        # 场景包根 = rule_set_path 的 rules/ 上一层（含 metrics/policy.yaml + agent_eval.yaml）
        scenario_pkg_dir = None
        if rule_set_path:
            _cand = Path(rule_set_path).resolve().parent.parent
            if (_cand / "metrics" / "policy.yaml").exists():
                scenario_pkg_dir = _cand

        # 5. 评估（run 产物自动识别 agent 模式）
        run_mode = _detect_run_mode(Path(package_dir))
        if run_mode == "agent":
            rprint("[blue]运行模式:[/blue] agent（执行器产物评估，继承自 run 清单）")

        result = evaluate_stage(
            Path(package_dir),
            judge_ctx,
            output_dir=output_dir,
            project=project,
            no_cache=no_cache,
            mode=run_mode,
            scenario_package_dir=scenario_pkg_dir,
        )

        # 6-8. trace 刷新 + 摘要 + SUT 身份回填 + 平台上报（共享段）
        finalize_eval(result, upload_override=upload, package_dir=package_dir)

    except Exception as e:
        rprint(f"[bold red]❌ 评估失败: {e}[/bold red]")
        raise typer.Exit(code=1) from e


@app.command()
def run(
    package: str | None = typer.Option(
        None,
        "--package",
        help="场景包引用（如 chat / chat:1.0.0）——考卷与 SUT 从包内解析（arch/16 §2.1）",
    ),
    task_set: str | None = typer.Option(
        None, "--task-set", help="任务集：文件路径，或包内名（与 --package 配合，如 default）"
    ),
    task_select: str | None = typer.Option(
        None,
        "--task",
        help="任务选择：ID / glob(safety_*) / 范围(3-6 或 a:b) / 逗号分隔 / !排除",
    ),
    sut_config: str | None = typer.Option(
        None,
        "--sut-config",
        help="被测系统配置路径（sut_config v2，yaml 文件或目录）；缺省从包内 sut_configs/ 解析",
    ),
    sut_name: str | None = typer.Option(
        None, "--sut-name", help="被测系统名（多系统时必填；唯一系统自动选中）"
    ),
    output_dir: str | None = typer.Option(
        None, "--output-dir", help="执行包输出目录（默认 ./workspace）"
    ),
    llm_role: str | None = typer.Option(
        None, "--llm-role", help="执行侧 LLM 角色（text|vision|agent，默认 agent）"
    ),
    max_turns: int | None = typer.Option(None, "--max-turns", help="单任务最大交互轮次"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="详细输出"),
) -> None:
    """执行被测 Agent（ExecutionAgent/DeepAgents 驱动），生成 ExecutionPackage。"""
    from pathlib import Path

    from agent_eval.cli._stages import execute_stage, resolve_run_inputs
    from agent_eval.core.exceptions import AgentEvalError
    from agent_eval.core.logging import setup_logging
    from agent_eval.storage.package import generate_run_id

    setup_logging(level="DEBUG" if verbose else "INFO")

    try:
        inputs = resolve_run_inputs(
            package,
            task_set=task_set,
            task_select=task_select,
            sut_config=sut_config,
            sut_name=sut_name,
        )
    except AgentEvalError as e:
        rprint(f"[red]配置加载失败:[/red] {e}")
        raise typer.Exit(code=1) from e

    run_id = generate_run_id()
    rprint(
        f"[blue]任务集:[/blue] {inputs.task_set_path}（{len(inputs.task_set_model.tasks)} 个任务）"
        + (f"（包 {inputs.resolved_pkg.manifest.ref}）" if inputs.resolved_pkg else "")
    )
    rprint(
        f"[blue]被测系统:[/blue] {inputs.sut.name}"
        f"（channel={inputs.sut.channel}, base_url={inputs.sut.base_url}）"
    )
    rprint(f"[blue]运行 ID:[/blue] {run_id}")

    workspace_root = Path(output_dir) if output_dir else Path("./workspace")
    try:
        packages = execute_stage(
            inputs,
            run_id=run_id,
            workspace_root=workspace_root,
            mode="run",
            llm_role=llm_role,
            max_turns=max_turns,
        )
    except AgentEvalError as e:
        rprint(f"[red]执行失败:[/red] {e}")
        raise typer.Exit(code=1) from e

    packages_run_dir = workspace_root / "runs" / run_id

    succeeded = sum(1 for p in packages if p.manifest.status == "success")
    rprint(
        f"[green]执行完成:[/green] {succeeded}/{len(packages)} 成功；"
        f"结构化日志: {workspace_root}/runs/{run_id}/agent_logs/"
    )
    for package in packages:
        status_color = "green" if package.manifest.status == "success" else "red"
        rprint(
            f"  [{status_color}]{package.manifest.status}[/{status_color}] "
            f"{package.manifest.task_id} → {package.output_dir or package.manifest.package_id}"
        )
    rprint(
        f"    评估: [blue]agent-eval eval --package-dir {packages_run_dir / 'packages'} "
        f"--package <场景包>[/blue]"
    )


@app.command()
def pipeline(
    package: str | None = typer.Option(
        None,
        "--package",
        help="场景包引用（如 chat / chat:1.0.0）——考卷/SUT/规则集一次解析；"
        "或用显式 --task-set/--sut-config/--rule-set 路径",
    ),
    task_set: str | None = typer.Option(
        None, "--task-set", help="任务集：文件路径，或包内名（缺省 manifest.default_task_set）"
    ),
    task: str | None = typer.Option(
        None,
        "--task",
        help="任务选择：ID / glob(safety_*) / 范围(3-6 或 a:b) / 逗号分隔 / !排除",
    ),
    sut_name: str | None = typer.Option(
        None, "--sut-name", help="被测系统名（多系统时必填；唯一系统自动选中）"
    ),
    sut_config: str | None = typer.Option(
        None, "--sut-config", help="显式 SUT 配置路径/目录（覆盖包内 sut_configs/）"
    ),
    rule_set: str | None = typer.Option(
        None, "--rule-set", help="包内规则集名（缺省取包内唯一规则集）"
    ),
    output_dir: str | None = typer.Option(
        None, "--output-dir", help="Workspace 根（默认 WORKSPACE_DIR 或 ./workspace）"
    ),
    llm_role: str | None = typer.Option(
        None, "--llm-role", help="执行侧 LLM 角色（text|vision|agent，默认 agent）"
    ),
    max_turns: int | None = typer.Option(None, "--max-turns", help="单任务最大交互轮次"),
    project: str | None = typer.Option(None, "--project", help="项目 ID"),
    upload: bool | None = typer.Option(
        None,
        "--upload/--no-upload",
        help="完成后推送可观测平台（覆盖 AGENT_EVAL_UPLOAD）",
    ),
    on_missing: str = typer.Option(
        "skip",
        "--on-missing-capability",
        help="所需能力不可用时：strict=阻断退出，skip=降级跳过并继续（默认）",
    ),
    no_cache: bool = typer.Option(
        False, "--no-cache", help="跳过评估缓存，强制重新评估（含 LLM 调用）"
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="详细输出"),
) -> None:
    """一体化流水线：执行被测 Agent → 评估 → 报告/上传（单 run_id 贯通，Sprint 9）。"""
    from agent_eval.cli._stages import (
        build_judge_context,
        evaluate_stage,
        execute_stage,
        finalize_eval,
        resolve_eval_inputs,
        resolve_run_inputs,
    )
    from agent_eval.core.exceptions import AgentEvalError
    from agent_eval.core.logging import setup_logging
    from agent_eval.storage.package import generate_run_id

    setup_logging(level="DEBUG" if verbose else "INFO")
    strict = on_missing == "strict"

    # ── 阶段 0：场景包一次解析（run 与 eval 共享 resolved_pkg）──
    try:
        inputs = resolve_run_inputs(
            package,
            task_set=task_set,
            task_select=task,
            sut_config=sut_config,
            sut_name=sut_name,
        )
        # 无包时 --rule-set 须为路径（resolve_eval_inputs 的 BadParameter 语义）
        rule_set_path = resolve_eval_inputs(package, rule_set)
    except Exception as e:
        rprint(f"[red]配置加载失败:[/red] {e}")
        raise typer.Exit(code=1) from e

    from agent_eval.config.paths import paths

    ws_root = Path(output_dir) if output_dir else paths.default_workspace
    run_id = generate_run_id()
    rprint(
        f"[blue]任务集:[/blue] {inputs.task_set_path}"
        f"（{len(inputs.task_set_model.tasks)} 个任务）"
        + (f"（包 {inputs.resolved_pkg.manifest.ref}）" if inputs.resolved_pkg else "")
    )
    rprint(
        f"[blue]被测系统:[/blue] {inputs.sut.name}"
        f"（channel={inputs.sut.channel}, base_url={inputs.sut.base_url}）"
    )
    rprint(f"[blue]规则集:[/blue] {rule_set_path}")
    rprint(f"[blue]运行 ID:[/blue] {run_id}（一体化流水线，mode=pipeline）")

    # ── 阶段 1：执行（清单 mode=pipeline，崩溃可溯源）──
    try:
        packages = execute_stage(
            inputs,
            run_id=run_id,
            workspace_root=ws_root,
            mode="pipeline",
            llm_role=llm_role,
            max_turns=max_turns,
        )
    except AgentEvalError as e:
        rprint(f"[red]执行失败:[/red] {e}")
        raise typer.Exit(code=1) from e

    succeeded = sum(1 for p in packages if p.manifest.status == "success")
    rprint(
        f"[green]执行完成:[/green] {succeeded}/{len(packages)} 成功；"
        f"结构化日志: {ws_root}/runs/{run_id}/agent_logs/"
    )

    # ── 阶段 2：评估（复用同一 run_id 的 RunWorkspace；清单合并 run 绑定字段）──
    run_dir = ws_root / "runs" / run_id
    packages_root = run_dir / "packages"
    run_manifest_extra = {
        "package_ref": (inputs.resolved_pkg.manifest.ref if inputs.resolved_pkg else None),
        "task_set": str(inputs.task_set_path),
        "sut": {"name": inputs.sut.name, "base_url": inputs.sut.base_url},
        "llm_role": llm_role or "agent",
        "packages": [str(p.output_dir or p.manifest.package_id) for p in packages],
    }
    try:
        judge_ctx = build_judge_context(rule_set_path, strict=strict)
        scenario_pkg_dir = inputs.resolved_pkg.root if inputs.resolved_pkg else None
        result = evaluate_stage(
            packages_root,
            judge_ctx,
            run=(ws_root, run_id),
            project=project,
            no_cache=no_cache,
            mode="pipeline",
            scenario_package_dir=scenario_pkg_dir,
            manifest_extra=run_manifest_extra,
        )
        finalize_eval(result, upload_override=upload, package_dir=str(packages_root))
    except Exception as e:
        rprint(f"[bold red]❌ 评估失败:[/bold red] {e}")
        raise typer.Exit(code=1) from e

    rprint(f"[green]✅ 流水线完成[/green] — {run_dir}")


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
    需配置 AGENT_EVAL_HOST / AGENT_EVAL_API_KEY。
    """
    import json as _json

    from agent_eval.evaluation.models import SampleResult
    from agent_eval.observability import ResultSink, load_config
    from agent_eval.observability.events import (
        build_artifact_event,
        build_constraint_event,
        build_run_event,
        build_sample_event,
    )
    from agent_eval.observability.sink import SinkReport

    run_dir = Path(workspace).resolve() / "runs" / run
    if not run_dir.exists():
        rprint(f"[red]运行目录不存在: {run_dir}[/red]")
        raise typer.Exit(code=1)

    summary_path = run_dir / "reports" / "summary.json"
    if not summary_path.exists():
        rprint(f"[red]缺少 summary.json: {summary_path}[/red]")
        raise typer.Exit(code=1)
    summary = _json.loads(summary_path.read_text(encoding="utf-8"))

    # 回填沿用真实运行模式：run 清单 mode=run → agent；mode=pipeline → pipeline
    manifest_path = run_dir / "run_manifest.json"
    run_mode = "eval_only"
    if manifest_path.exists():
        try:
            _m = _json.loads(manifest_path.read_text(encoding="utf-8")).get("mode")
            if _m == "run":
                run_mode = "agent"
            elif _m == "pipeline":
                run_mode = "pipeline"
        except (OSError, ValueError):
            pass

    env_override: dict[str, str] = {}
    if project:
        env_override["AGENT_EVAL_PROJECT"] = project
    # upload 子命令默认强制开启上传
    cfg = load_config(upload_override=True)
    if not cfg.has_credentials():
        rprint("[red]未配置凭据：请设置 AGENT_EVAL_HOST / AGENT_EVAL_API_KEY[/red]")
        raise typer.Exit(code=1)

    metrics = summary.get("metrics", {})
    # 用 build_run_event 重建 run 事件（附带场景化指标键 + scenario_id + 运行配置快照）
    from agent_eval.evaluation.models import MetricsReport

    # summary["metrics"] 已是场景化指标 dict（key=metric_id）；avg_time_ms 为顶层过程元数据
    report = MetricsReport(
        run_id=summary.get("run_id", run),
        total_samples=summary.get("total_samples", 0),
        metrics={
            k: float(v)
            for k, v in metrics.items()
            if k != "avg_time_ms" and isinstance(v, int | float)
        },
        avg_time_ms=summary.get("avg_time_ms", metrics.get("avg_time_ms", 0.0)),
    )
    # 从 summary 重建 ScenarioConfig，使回填 run 的 scenario_id/指标定义与原运行一致
    # （S2-13：不再回退 courseware）。scenario_id 由指标 id 前缀推导（如 code:delivery_rate → code）。
    from agent_eval.evaluation.scenario.models import (
        AggregationPolicy,
        MetricDefinition,
        ScenarioConfig,
    )

    mdefs_raw = summary.get("metric_definitions") or []
    backfill_sid = str(mdefs_raw[0]["id"]).split(":", 1)[0] if mdefs_raw else "courseware"
    scenario_config = ScenarioConfig(
        scenario_id=backfill_sid,
        aggregation_policy=AggregationPolicy(
            id=f"{backfill_sid}-backfill", scenario_id=backfill_sid, stage_weights=[]
        ),
        metric_definitions=[MetricDefinition.model_validate(m) for m in mdefs_raw],
    )
    events: list[dict[str, Any]] = [
        build_run_event(
            report,
            mode=run_mode,
            rule_set_version=summary.get("rule_set_version"),
            summary_report=summary.get("summary_report"),
            scenario_config=scenario_config,
        ),
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

    # ── artifacts: 扫描 evidence/ 目录上传截图 + judge 记录；扫描 package 上传原始文件 ──
    run_id_str = summary.get("run_id", run)
    sink = ResultSink(cfg)
    art_report = SinkReport(enabled=True)
    artifact_count = 0

    # 从 run_manifest 获取 package_dir（原始产出物所在）
    manifest_path = run_dir / "run_manifest.json"
    package_dir_str = ""
    if manifest_path.exists():
        package_dir_str = _json.loads(manifest_path.read_text(encoding="utf-8")).get(
            "package_dir", ""
        )

    if results_dir.exists():
        for task_dir in sorted(p for p in results_dir.iterdir() if p.is_dir()):
            report_path = task_dir / "report.json"
            if not report_path.exists():
                continue
            try:
                sample = SampleResult.from_dict(
                    _json.loads(report_path.read_text(encoding="utf-8"))
                )
            except Exception:
                continue

            evidence_dir = task_dir / "evidence"
            if evidence_dir.exists():
                # 截图（.png）
                for shot in sorted(evidence_dir.glob("*.png")):
                    ok_obj = sink._upload_artifact(
                        shot,
                        external_run_id=run_id_str,
                        external_sample_id=sample.sample_id,
                        kind="screenshot",
                        content_type="image/png",
                        original_name=shot.name,
                        report=art_report,
                    )
                    if ok_obj:
                        events.append(
                            build_artifact_event(
                                external_run_id=run_id_str,
                                external_sample_id=sample.sample_id,
                                kind="screenshot",
                                object_key=ok_obj,
                                content_type="image/png",
                                size_bytes=shot.stat().st_size,
                                original_name=shot.name,
                            )
                        )
                        artifact_count += 1
                # judge 记录（judge_*.json）
                for jf in sorted(evidence_dir.glob("judge_*.json")):
                    ok_obj = sink._upload_artifact(
                        jf,
                        external_run_id=run_id_str,
                        external_sample_id=sample.sample_id,
                        kind="judge_record",
                        content_type="application/json",
                        original_name=jf.name,
                        report=art_report,
                    )
                    if ok_obj:
                        events.append(
                            build_artifact_event(
                                external_run_id=run_id_str,
                                external_sample_id=sample.sample_id,
                                kind="judge_record",
                                object_key=ok_obj,
                                content_type="application/json",
                                size_bytes=jf.stat().st_size,
                                original_name=jf.name,
                            )
                        )
                        artifact_count += 1

    # 原始产出物：按样本归属上传（output/ 产物 + 执行包技术文件分类）——需样本列表
    if package_dir_str:
        pkg = Path(package_dir_str)
        if pkg.exists():
            # 从 results/ 重建样本引用（sample_id = task_id），供归属
            from types import SimpleNamespace

            sids = (
                [
                    d.name
                    for d in (run_dir / "results").iterdir()
                    if d.is_dir() and (d / "report.json").exists()
                ]
                if (run_dir / "results").is_dir()
                else []
            )
            if sids:
                src_events = sink._upload_package_artifacts(
                    pkg, run_id_str, [SimpleNamespace(sample_id=sid) for sid in sids], art_report
                )
                events.extend(src_events)
                artifact_count += len(src_events)

    rprint(
        f"[blue]回填:[/blue] 运行 {run}，样本 {sample_count}，"
        f"事件 {len(events)}（含 {artifact_count} 制品）"
    )
    sent, queued = sink.dispatch(events)
    rprint(f"[green]✓ 回填完成[/green] 已发送 {sent}、入队 {queued}")


@app.command()
def version() -> None:
    """显示版本信息。"""
    from agent_eval import __version__

    rprint(f"agent-eval v{__version__}")


if __name__ == "__main__":
    app()
