"""agent-eval run / pipeline — 在线执行与一体化流水线（编排复用 _stages 五阶段）。

``pipeline`` 命令为 ``pipeline_core``（编排单一真相源）的薄壳：用法解析（BadParameter）+ 渲染器装配 + 失败/门禁
红字 + 退出码——编排零复制，CLI 外部行为零变化（黄金快照锁定）。
"""

from __future__ import annotations

from pathlib import Path

import typer

from agent_eval.cli._common import ensure_sut_credentials, rprint
from agent_eval.cli.pipeline_core import (
    PipelineOutcome,
    PipelineParams,
    _run_json_payload,
    pipeline_core,
)


def run(
    package: str | None = typer.Option(
        None,
        "--package",
        help="场景包引用（如 chat / chat:1.0.0）——考卷与 SUT 从包内解析",
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
    max_turns: int | None = typer.Option(
        None, "--max-turns", help="已废弃：轮次预算由 interaction_policy 声明，此参数不再生效"
    ),
    log_level: str = typer.Option(
        "normal",
        "--log-level",
        help="执行日志档位：quiet=仅结果行 | normal=默认进度 | "
        "verbose=过程事件（SUT/judge/重试） | debug=全量原文",
    ),
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
        log_level=log_level,
    )


def execute_run(
    package: str | None = None,
    task_set: str | None = None,
    task_select: str | None = None,
    sut_config: str | None = None,
    sut_name: str | None = None,
    output_dir: str | None = None,
    llm_role: str | None = None,
    max_turns: int | None = None,
    log_level: str = "normal",
) -> None:
    """执行动作（纯函数，向导/工作台复用；理由见 execute_eval docstring）。"""

    from agent_eval.cli._stages import execute_stage, resolve_run_inputs
    from agent_eval.cli.console.output import emit_json, is_json
    from agent_eval.cli.console.render import print_task_table, progress_mode, stage_progress
    from agent_eval.core.exceptions import AgentEvalError
    from agent_eval.core.logging import (
        install_exec_event_handler,
        resolve_logging_level,
        setup_logging,
    )
    from agent_eval.storage.package import generate_run_id

    setup_logging(level=resolve_logging_level(log_level))
    install_exec_event_handler(enabled=log_level in ("verbose", "debug"))

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
        with stage_progress(mode=progress_mode(log_level)) as sp:
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
    max_turns: int | None = typer.Option(
        None, "--max-turns", help="已废弃：轮次预算由 interaction_policy 声明，此参数不再生效"
    ),
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
    gate: str = typer.Option(
        "off",
        "--gate",
        help="质量门禁：off=不判定（默认）| strict=逐项声明阈值卡点 | <float>=reward 综合得分卡点",
    ),
    report_formats: list[str] = typer.Option(
        None,
        "--report-formats",
        help="追加报告格式（可重复/逗号分隔）：junit=reports/junit.xml，txt=reports/summary.txt",
    ),
    log_level: str = typer.Option(
        "normal",
        "--log-level",
        help="执行日志档位：quiet=仅结果行 | normal=默认进度 | "
        "verbose=过程事件（SUT/judge/重试） | debug=全量原文",
    ),
) -> None:
    """一体化流水线：执行被测 Agent → 评估 → 报告/上传（单 run_id 贯通）。"""
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
        gate=gate,
        report_formats=list(report_formats) if report_formats else None,
        log_level=log_level,
    )


def _parse_report_formats(raw: list[str] | None) -> list[str]:
    """解析 --report-formats（可重复/逗号分隔），合法值 junit/txt，非法即 BadParameter。"""
    formats: list[str] = []
    for item in raw or []:
        for part in item.split(","):
            fmt = part.strip().lower()
            if not fmt:
                continue
            if fmt not in ("junit", "txt"):
                raise typer.BadParameter(
                    f"不支持的报告格式: {part!r}（合法值: junit, txt）",
                )
            if fmt not in formats:
                formats.append(fmt)
    return formats


def _render_outcome(outcome: PipelineOutcome) -> None:
    """失败/门禁红字（文案与薄壳化前逐字一致；done/cancelled 无输出——CLI cancel 恒 None）。"""
    if outcome.stage == "gate_config":
        rprint(f"[red]门禁配置错误:[/red] {outcome.error}")
    elif outcome.stage == "resolve":
        rprint(f"[red]配置加载失败:[/red] {outcome.error}")
    elif outcome.stage == "credentials":
        rprint(f"[red]凭证缺失:[/red] {outcome.error}")
    elif outcome.stage == "execute":
        rprint(f"[red]执行失败:[/red] {outcome.error}")
    elif outcome.stage == "evaluate":
        rprint(f"[bold red]❌ 评估失败:[/bold red] {outcome.error}")
    elif outcome.stage == "gate":
        gate = outcome.gate or {}  # gate 阶段语义上必非 None——类型收窄兜底
        failures = "；".join(gate.get("failures") or [])
        rprint(
            f"[red]❌ 质量门禁未达标[/red]（--gate {gate.get('mode')}）: "
            f"{failures or '详见 summary.json gate 字段'}"
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
    gate: str = "off",
    report_formats: list[str] | None = None,
    log_level: str = "normal",
) -> None:
    """流水线动作（pipeline_core 薄壳，向导/工作台复用）。

    退出码契约（CI 按此映射构建状态）：
    0=成功（含门禁通过）| 1=配置/执行失败 | 3=质量门禁未达标。
    """
    from agent_eval.cli.console.output import emit_json, is_json
    from agent_eval.cli.console.pipeline_render import make_pipeline_renderer

    # 用法解析留壳（BadParameter=exit 2 是 CLI 语义，不进 core）
    formats = _parse_report_formats(report_formats)
    params = PipelineParams(
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
        gate=gate,
        report_formats=formats,
        log_level=log_level,
    )
    renderer = make_pipeline_renderer(log_level)
    outcome = pipeline_core(
        params,
        progress=renderer.on_progress,
        cancel_event=None,
        credential_filler=ensure_sut_credentials,
    )
    if outcome.payload is not None and is_json():
        emit_json(outcome.payload)
    _render_outcome(outcome)
    if outcome.exit_code:
        raise typer.Exit(code=outcome.exit_code)
