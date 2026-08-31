"""agent-eval eval — 对 ExecutionPackage 执行评估（eval-only 路径）。"""

from __future__ import annotations

from pathlib import Path

import typer

from agent_eval.cli._common import rprint


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
    execute_eval(
        package_dir=package_dir,
        rule_set=rule_set,
        package=package,
        output_dir=output_dir,
        eval_mode=eval_mode,
        project=project,
        upload=upload,
        on_missing=on_missing,
        no_cache=no_cache,
        verbose=verbose,
    )


def execute_eval(
    package_dir: str,
    rule_set: str | None = None,
    package: str | None = None,
    output_dir: str | None = None,
    eval_mode: str = "pipeline",
    project: str | None = None,
    upload: bool | None = None,
    on_missing: str = "skip",
    no_cache: bool = False,
    verbose: bool = False,
) -> None:
    """评估动作（纯函数，向导/工作台复用）。

    直接以 Python 调用命令函数时，typer.Option 默认值是 OptionInfo 元对象
    （仅经 CLI 分发才注入真实值），曾致 ``Path(OptionInfo)`` TypeError——
    故命令体只留薄壳，业务下沉本动作（arch/15 §2.2 组织约定 2）。
    """
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
