"""run / eval / pipeline / suite 共享编排段（Sprint 9 一体化）。

从 cli/main.py 的 run 与 eval 命令收敛而来，保持行为等价：
- resolve_run_inputs：场景包 + 考卷 + SUT 一次解析（run 437-472 ≈ suite 86-100）
- resolve_eval_inputs：规则集路径解析（原 _resolve_rule_set_path）
- build_judge_context：RuleSet 加载 + LLM 配置 + Judge 编排 + 能力/视觉派生
- execute_stage：channel + ExecutionAgent 执行 + 运行清单（suite 由此补上清单）
- evaluate_stage：评估（standalone 自建 run；传入 (ws_root, run_id) 则复用同一 run）
- finalize_eval：trace 刷新 + 摘要 + SUT 身份回填 + 平台上报
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rich import print as rprint

from agent_eval.core.exceptions import AgentEvalError
from agent_eval.packages.manifest import ResolvedPackage


@dataclass
class RunInputs:
    """执行阶段输入（一次解析，run/pipeline/suite 共享）。"""

    resolved_pkg: ResolvedPackage | None
    task_set_path: Path
    task_set_model: Any  # TaskSet（已应用 --task 过滤）
    config_path: Path
    sut: Any  # SUTSystemConfig


@dataclass
class JudgeContext:
    """评估阶段上下文（RuleSet + Judge 编排 + 视觉派生）。"""

    rule_set_obj: Any  # RuleSet
    judge_orch: Any | None = None
    llm_signature: str = "no-llm"
    want_vision: bool = False
    renderer: Any | None = None  # PlaywrightScreenshotRenderer（用毕须 close）
    rule_set_path: str | None = None
    prompts_dir: str | None = field(default=None)


def write_run_manifest(run_dir: Path, payload: dict[str, Any]) -> None:
    """写运行清单（runs/{run_id}/run_manifest.json，绑定显式化第一步）。"""
    import json

    try:
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "run_manifest.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError as e:
        rprint(f"[yellow]⚠ 运行清单写入失败: {e}[/yellow]")


def resolve_run_inputs(
    package: str | None,
    *,
    task_set: str | None = None,
    task_select: str | None = None,
    sut_config: str | None = None,
    sut_name: str | None = None,
) -> RunInputs:
    """解析执行输入：显式路径优先，缺省从场景包内取（arch/13 §4.1）。"""
    from agent_eval.config.loader import ConfigLoader
    from agent_eval.execution.registry import SUTRegistry
    from agent_eval.packages.assets import (
        resolve_sut_configs_dir,
        resolve_task_set_path,
        select_tasks,
    )
    from agent_eval.packages.manager import PackageManager

    resolved_pkg: ResolvedPackage | None = (
        PackageManager().resolve_ref(package) if package else None
    )

    task_set_path: Path | None = Path(task_set) if task_set and Path(task_set).exists() else None
    if task_set_path is None:
        if resolved_pkg is not None:
            task_set_path = resolve_task_set_path(resolved_pkg, task_set)
        else:
            raise AgentEvalError("必须提供 --task-set（路径）或 --package（包内任务集解析）")

    if sut_config and Path(sut_config).exists():
        config_path = Path(sut_config)
    elif resolved_pkg is not None:
        config_path = resolve_sut_configs_dir(resolved_pkg)
    else:
        raise AgentEvalError("必须提供 --sut-config（路径）或 --package（包内 sut_configs/ 解析）")

    registry = (
        SUTRegistry.load_dir(config_path) if config_path.is_dir() else SUTRegistry.load(config_path)
    )
    sut = registry.get(sut_name) if sut_name else registry.default
    task_set_model = ConfigLoader.load_task_set(task_set_path)
    task_set_model.tasks = select_tasks(task_set_model.tasks, task_select)
    return RunInputs(
        resolved_pkg=resolved_pkg,
        task_set_path=task_set_path,
        task_set_model=task_set_model,
        config_path=config_path,
        sut=sut,
    )


def resolve_eval_inputs(package: str | None, rule_set: str | None) -> str:
    """解析规则集路径（原 cli/main.py._resolve_rule_set_path 原样迁移，行为等价）。

    - 都未给 → 报错。
    - 仅 --rule-set → 直接返回（旧流程，路径或名称由调用方语义决定）。
    - --package → PackageManager.resolve_ref 取包根；--rule-set 作包内名称或显式路径，
      缺省取包内唯一规则集（多个则列出可用并报错）。
    """
    import typer

    if package is None:
        if not rule_set:
            raise typer.BadParameter("必须提供 --rule-set（路径/名称）或 --package（场景包引用）")
        return rule_set

    from agent_eval.packages import PackageManager

    pkg = PackageManager().resolve_ref(package)
    rules_dir = pkg.rules_dir
    # 显式路径优先
    if rule_set and ("/" in rule_set or rule_set.endswith((".yaml", ".yml"))):
        return rule_set
    name = rule_set
    if not name:
        avail = sorted(p.stem for p in rules_dir.glob("*.yaml"))
        if len(avail) == 1:
            name = avail[0]
        elif not avail:
            raise typer.BadParameter(f"包 {pkg.manifest.ref} 的 rules/ 下无规则集")
        else:
            raise typer.BadParameter(
                f"包 {pkg.manifest.ref} 含多个规则集，请用 --rule-set 指定：{', '.join(avail)}"
            )
    path = rules_dir / f"{name}.yaml"
    if not path.exists():
        avail = ", ".join(sorted(p.stem for p in rules_dir.glob("*.yaml"))) or "（无）"
        raise typer.BadParameter(f"包 {pkg.manifest.ref} 内未找到规则集 '{name}'；可用: {avail}")
    return str(path)


def build_judge_context(rule_set_path: str, *, strict: bool = False) -> JudgeContext:
    """加载 RuleSet + LLM/Judge/视觉派生（原 eval 命令 1-4 段，行为等价）。"""
    import agent_eval.evaluation.evaluators  # noqa: F401  触发注册
    from agent_eval.cli._common import _check_llm_availability, _init_judge_orchestrator
    from agent_eval.config.llm_resolution import (
        llm_signature as _llm_sig,
    )
    from agent_eval.config.llm_resolution import (
        resolve_llm_config,
    )
    from agent_eval.config.loader import ConfigLoader
    from agent_eval.core.types import Capability
    from agent_eval.evaluation.capability import CapabilityResolver
    from agent_eval.evaluation.registry import registry

    rule_set_obj = ConfigLoader.load_rule_set(rule_set_path)

    try:
        llm_cfg = resolve_llm_config()
    except Exception as e:  # noqa: BLE001 — LLM 不可用时 Judge 降级（原语义）
        llm_cfg = None
        rprint(f"[yellow]⚠ LLM 配置不可用，LLM 评估器将降级: {e}[/yellow]")

    prompts_dir: str | None = None
    _pp = Path(rule_set_path).resolve().parent.parent / "prompts"
    if _pp.exists():
        prompts_dir = str(_pp)
    judge_orch = _init_judge_orchestrator(llm_cfg, prompts_dir=prompts_dir)
    llm_signature = _llm_sig(llm_cfg) if llm_cfg is not None else "no-llm"
    _check_llm_availability(rule_set_obj, judge_orch, strict)

    required = CapabilityResolver(registry).resolve(rule_set_obj)
    want_vision = Capability.VISION in required.capabilities
    renderer = None
    if want_vision:
        try:
            from agent_eval.evaluation.vision import PlaywrightScreenshotRenderer

            renderer = PlaywrightScreenshotRenderer()
            rprint("[blue]视觉评估:[/blue] 已启用")
        except Exception as e:  # noqa: BLE001 — 渲染器初始化失败降级（原语义）
            rprint(f"[yellow]⚠ 视觉渲染器初始化失败，视觉评估器将降级: {e}[/yellow]")

    return JudgeContext(
        rule_set_obj=rule_set_obj,
        judge_orch=judge_orch,
        llm_signature=llm_signature,
        want_vision=want_vision,
        renderer=renderer,
        rule_set_path=rule_set_path,
        prompts_dir=prompts_dir,
    )


def execute_stage(
    run_inputs: RunInputs,
    *,
    run_id: str,
    workspace_root: Path,
    mode: str = "run",
    llm_role: str | None = None,
    max_turns: int | None = None,
) -> list[Any]:
    """执行被测 Agent 并写运行清单（原 run 命令执行段，行为等价）。"""
    from agent_eval.agent.execution_agent import ExecutionAgent
    from agent_eval.agent.protocol_tools import AgentProtocolToolServer
    from agent_eval.cli.cmds.secrets import ensure_sut_credentials
    from agent_eval.execution.channels.base import create_channel
    from agent_eval.execution.models import AgentConfig

    sut = run_inputs.sut
    # 凭证缺失：交互终端引导补录缺失字段后继续；--no-input 保持 fail fast
    # （不进 Agent 循环烧轮次）
    ensure_sut_credentials(sut)
    channel = create_channel(sut)
    protocol_tools = AgentProtocolToolServer(
        channel, default_metadata={"eval_run_id": run_id, "sut_name": sut.name}
    )
    agent = ExecutionAgent(
        AgentConfig(
            llm_role=llm_role or "agent",
            max_turns=max_turns or 20,
            workspace_dir=workspace_root,
        ),
        extra_tool_servers=[protocol_tools],
    )

    async def _run_and_close() -> tuple[str, list[Any]]:
        # 通道关闭必须与 run 同一 event loop（httpx client 绑定创建时的 loop，
        # 另起 asyncio.run 关旧 loop 上的 client 会 RuntimeError: Event loop is closed）
        try:
            return await agent.run_task_set(run_inputs.task_set_model, run_id=run_id)
        finally:
            await channel.aclose()

    _, packages = asyncio.run(_run_and_close())

    # 运行清单（W7 + 绑定显式化，arch/13 §二十一）
    write_run_manifest(
        workspace_root / "runs" / run_id,
        {
            "mode": mode,
            "run_id": run_id,
            "package_ref": (
                run_inputs.resolved_pkg.manifest.ref if run_inputs.resolved_pkg else None
            ),
            "task_set": str(run_inputs.task_set_path),
            "sut": {"name": sut.name, "base_url": sut.base_url},
            "llm_role": llm_role or "agent",
            "packages": [str(p.output_dir or p.manifest.package_id) for p in packages],
        },
    )
    return packages


def evaluate_stage(
    packages_dir: Path,
    judge_ctx: JudgeContext,
    *,
    output_dir: str | None = None,
    run: tuple[Path, str] | None = None,
    project: str | None = None,
    no_cache: bool = False,
    mode: str = "eval_only",
    scenario_package_dir: Path | None = None,
    manifest_extra: dict[str, Any] | None = None,
) -> Any:
    """评估（原 eval 命令 5 段）。

    - standalone（run=None）：Workspace(output_dir)，eval_only 自建 run_id；
    - run=(ws_root, run_id)：复用既有 RunWorkspace（pipeline 单 run_id 贯通），
      并补建 reports/results（执行阶段不创建）。
    - manifest_extra：pipeline 传执行阶段绑定字段，eval_only 写清单时合并（单次原子写）。
    """
    from agent_eval.orchestrator.orchestrator import Orchestrator
    from agent_eval.storage.workspace import Workspace

    if run is not None:
        ws_root, run_id = run
        run_ws = Workspace(ws_root).get_run(run_id)
        run_ws.ensure_dirs()
        ws = Workspace(ws_root)
        run_workspace: Any = run_ws
    else:
        ws = Workspace(output_dir) if output_dir else Workspace()
        run_workspace = None

    orch = Orchestrator(workspace=ws)
    try:
        return orch.eval_only(
            Path(packages_dir),
            judge_ctx.rule_set_obj,
            judge_orchestrator=judge_ctx.judge_orch,
            project=project,
            with_vision=judge_ctx.want_vision,
            screenshot_renderer=judge_ctx.renderer,
            llm_signature=judge_ctx.llm_signature,
            no_cache=no_cache,
            scenario_package_dir=scenario_package_dir,
            mode=mode,
            run_workspace=run_workspace,
            manifest_extra=manifest_extra,
        )
    finally:
        if judge_ctx.renderer is not None:
            judge_ctx.renderer.close()


def finalize_eval(result: Any, *, upload_override: bool | None, package_dir: str) -> None:
    """评估收尾：trace 刷新 + 摘要 + SUT 身份回填 + 平台上报（原 eval 6-8 段）。"""
    from agent_eval.cli._common import _flush_observability, _print_summary
    from agent_eval.llm.tracing import flush_traces

    flush_traces()
    _print_summary(result.report)
    rprint("[green]✅ 评估完成[/green] — 结果已保存至 workspace")

    # W6：回填 SUT 身份（包 metadata.sut_name@sut_version → run event）
    if result.samples:
        sample_meta = getattr(result.samples[0], "metadata", None) or {}
        result.sut_version = str(
            sample_meta.get("sut_version") or sample_meta.get("sut_name") or ""
        )

    _flush_observability(result, upload_override=upload_override, package_dir=package_dir)
