"""agent-eval run / pipeline — 在线执行与一体化流水线（编排复用 _stages 五阶段）。"""

from __future__ import annotations

from pathlib import Path

import typer

from agent_eval.cli._common import ensure_sut_credentials, rprint


def run(
    package: str | None = typer.Option(
        None,
        "--package",
        help="场景包引用（如 chat / chat:1.0.0）——考卷与 SUT 从包内解析（arch/13 §4.1）",
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
    execute_run(
        package=package,
        task_set=task_set,
        task_select=task_select,
        sut_config=sut_config,
        sut_name=sut_name,
        output_dir=output_dir,
        llm_role=llm_role,
        max_turns=max_turns,
        verbose=verbose,
    )


def _run_json_payload(
    *,
    run_id: str,
    mode: str,
    inputs: object,
    packages: list,
    run_dir: Path,
    metrics: dict | None = None,
    total_samples: int | None = None,
) -> dict:
    """run/pipeline 的机器可读结果（F-C-INTEG-02）。"""
    payload: dict = {
        "run_id": run_id,
        "mode": mode,
        "package_ref": (inputs.resolved_pkg.manifest.ref if inputs.resolved_pkg else None),
        "task_set": str(inputs.task_set_path),
        "sut": {"name": inputs.sut.name, "base_url": inputs.sut.base_url},
        "total": len(packages),
        "succeeded": sum(1 for p in packages if p.manifest.status == "success"),
        "packages": [
            {
                "task_id": p.manifest.task_id,
                "status": p.manifest.status,
                "output": str(p.output_dir or p.manifest.package_id),
            }
            for p in packages
        ],
        "run_dir": str(run_dir),
    }
    if metrics is not None:
        payload["metrics"] = metrics
        payload["total_samples"] = total_samples
    return payload


def execute_run(
    package: str | None = None,
    task_set: str | None = None,
    task_select: str | None = None,
    sut_config: str | None = None,
    sut_name: str | None = None,
    output_dir: str | None = None,
    llm_role: str | None = None,
    max_turns: int | None = None,
    verbose: bool = False,
) -> None:
    """执行动作（纯函数，向导/工作台复用；理由见 execute_eval docstring）。"""
    from pathlib import Path

    from agent_eval.cli._stages import execute_stage, resolve_run_inputs
    from agent_eval.cli.console.output import emit_json, is_json
    from agent_eval.cli.console.render import print_task_table, stage_progress
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

    # 凭证保障在进度视图启动前：缺失当场引导补录（stage_progress 转轮会刷掉
    # 输入提示行，实测提示被「执行 N 个任务」掩盖）；取消/--no-input 则 fail fast
    try:
        ensure_sut_credentials(inputs.sut)
    except AgentEvalError as e:
        rprint(f"[red]凭证缺失:[/red] {e}")
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

    # workspace 根统一走 paths（WORKSPACE_DIR 生效）——曾硬编码 ./workspace，
    # run 与 runs list/pipeline 各读各的，还把 pytest 执行段漏进真实 workspace
    from agent_eval.config.paths import paths as _paths

    workspace_root = Path(output_dir) if output_dir else _paths.default_workspace
    try:
        with stage_progress(enabled=not verbose and not is_json()) as sp:
            sp.advance(f"执行 {len(inputs.task_set_model.tasks)} 个任务（SUT: {inputs.sut.name}）")
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
    print_task_table(packages)
    if is_json():
        emit_json(
            _run_json_payload(
                run_id=run_id,
                mode="run",
                inputs=inputs,
                packages=packages,
                run_dir=packages_run_dir,
            )
        )
        return
    rprint(
        f"    评估: [blue]agent-eval eval --package-dir {packages_run_dir / 'packages'} "
        f"--package <场景包>[/blue]"
    )


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
    execute_pipeline(
        package=package,
        task_set=task_set,
        task=task,
        sut_name=sut_name,
        sut_config=sut_config,
        rule_set=rule_set,
        output_dir=output_dir,
        llm_role=llm_role,
        max_turns=max_turns,
        project=project,
        upload=upload,
        on_missing=on_missing,
        no_cache=no_cache,
        verbose=verbose,
    )


def execute_pipeline(
    package: str | None = None,
    task_set: str | None = None,
    task: str | None = None,
    sut_name: str | None = None,
    sut_config: str | None = None,
    rule_set: str | None = None,
    output_dir: str | None = None,
    llm_role: str | None = None,
    max_turns: int | None = None,
    project: str | None = None,
    upload: bool | None = None,
    on_missing: str = "skip",
    no_cache: bool = False,
    verbose: bool = False,
) -> None:
    """流水线动作（纯函数，向导/工作台复用；组织约定见 arch/15 §2.2）。"""
    from agent_eval.cli._stages import (
        build_judge_context,
        evaluate_stage,
        execute_stage,
        finalize_eval,
        resolve_eval_inputs,
        resolve_run_inputs,
    )
    from agent_eval.cli.console.output import emit_json, is_json
    from agent_eval.cli.console.render import print_task_table, stage_progress
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

    # 凭证保障在进度视图启动前（同 execute_run：转轮会刷掉补录输入提示行）
    try:
        ensure_sut_credentials(inputs.sut)
    except AgentEvalError as e:
        rprint(f"[red]凭证缺失:[/red] {e}")
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
        with stage_progress(enabled=not verbose and not is_json()) as sp:
            sp.advance(f"执行 {len(inputs.task_set_model.tasks)} 个任务（SUT: {inputs.sut.name}）")
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
    print_task_table(packages)

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
        with stage_progress(enabled=not verbose and not is_json()) as sp:
            sp.advance("评估（Rule-based + LLM Judge）")
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
            sp.advance("上报 / 收尾")
            finalize_eval(result, upload_override=upload, package_dir=str(packages_root))
    except Exception as e:
        rprint(f"[bold red]❌ 评估失败:[/bold red] {e}")
        raise typer.Exit(code=1) from e

    rprint(f"[green]✅ 流水线完成[/green] — {run_dir}")
    if is_json():
        emit_json(
            _run_json_payload(
                run_id=run_id,
                mode="pipeline",
                inputs=inputs,
                packages=packages,
                run_dir=run_dir,
                metrics=dict(result.metrics),
                total_samples=result.total_samples,
            )
        )
