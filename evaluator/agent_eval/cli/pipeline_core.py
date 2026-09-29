"""管线编排纯函数。

``pipeline_core(params, *, progress, cancel_event, credential_filler) → PipelineOutcome``：
无渲染 / 无交互 / 无 typer——终端呈现经 progress 事件（``console.pipeline_render``
的 PipelineRenderer 消费），凭证交互经 credential_filler 钩子（壳注入：CLI=
``ensure_sut_credentials``，Agent 域=ask_fn 补录循环），Ctrl+C 协作取消经
cancel_event（任务边界粒度，透传 ``run_task_set``）。

CLI 壳（``cmds/execute.execute_pipeline``）与 WorkbenchAgent 执行域
（``agent/workbench/execution``）共用本函数——两宿主自此零编排复制。
退出码契约**返回而非 raise**：0=成功（含门禁通过）|
1=配置/执行失败 | 3=质量门禁未达标 | 130=协作取消（仅 Agent 域可达，
CLI 的 cancel_event 恒 None）。
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

ProgressFn = Callable[["PipelineStage", dict[str, Any]], None]
CredentialFiller = Callable[[Any], None]


class PipelineStage(str, Enum):
    """progress 事件枚举（渲染指令；发射顺序=CLI 现行 with 块边界）。"""

    RESOLVE_INFO = "resolve_info"  # 4 行信息行（任务集/被测系统/规则集/运行 ID）
    EXECUTE = "execute"  # 进入执行进度视图
    EXECUTE_DONE = "execute_done"  # 退出执行视图 + 执行完成行 + 任务表
    EVALUATE = "evaluate"  # 进入评估进度视图
    FINALIZE = "finalize"  # advance「上报 / 收尾」
    SUMMARY = "summary"  # 摘要表 + 「评估完成」行
    UPLOAD_START = "upload_start"  # 「推送结果中…」横幅（enabled 时）
    UPLOAD = "upload"  # 上报回执渲染
    DONE = "done"  # 退出评估视图 + 「流水线完成」行
    ABORT = "abort"  # 异常路径幂等关进度视图（零输出，= with 块异常退出）


@dataclass(frozen=True, slots=True)
class PipelineParams:
    """pipeline_core 入参（字段= CLI ``pipeline`` 命令 17 参数原样）。

    ``report_formats`` 传**已解析**形态（壳负责 ``_parse_report_formats``——
    用法错误 BadParameter 是 CLI 语义，不进 core）；``log_level`` 由 core 驱动
    ``setup_logging``（进程全局突变，Agent 域经 render_bridge 快照恢复）。
    """

    package: str | None = None
    task_set: str | None = None
    task: str | None = None
    sut_name: str | None = None
    sut_config: str | None = None
    rule_set: str | None = None
    output_dir: str | None = None
    llm_role: str | None = None
    max_turns: int | None = None  # 已废弃参数，透传保持兼容
    project: str | None = None
    upload: bool | None = None
    on_missing: str = "skip"
    no_cache: bool = False
    concurrency: int = 1  # 样本级并发评估（与 eval --concurrency 同语义，透传 evaluate_stage）
    gate: str = "off"
    report_formats: list[str] | None = None
    log_level: str = "normal"


@dataclass(frozen=True, slots=True)
class PipelineOutcome:
    """pipeline_core 终态（stage+exit_code+机器可读产物，壳据此渲染/退出）。"""

    stage: str  # done|gate_config|resolve|credentials|execute|evaluate|gate|cancelled
    exit_code: int  # 0|1|3；cancelled=130（CLI 不可达）
    error: str = ""  # str(异常)；""=无异常
    error_type: str = ""  # 异常类名
    cancelled: bool = False
    run_id: str = ""
    run_dir: str = ""
    metrics: dict[str, float] | None = None
    total_samples: int | None = None
    gate: dict[str, Any] | None = None  # EvalResult.gate（enabled/passed/mode/failures）
    upload_receipt: dict[str, Any] | None = None  # observability_flush 回执
    payload: dict[str, Any] | None = None  # _run_json_payload 产物（成功/门禁失败均带）
    result: Any = None  # EvalResult 本体（Agent 摘要/门禁明细用；CLI 壳不读）

    @property
    def ok(self) -> bool:
        return self.exit_code == 0


def _run_json_payload(
    *,
    run_id: str,
    mode: str,
    inputs: Any,
    packages: list[Any],
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


def pipeline_core(
    params: PipelineParams,
    *,
    progress: ProgressFn | None = None,
    cancel_event: threading.Event | None = None,
    credential_filler: CredentialFiller | None = None,
) -> PipelineOutcome:
    """一体化流水线编排（执行 → 评估 → 收尾/上报；纯函数，见模块 docstring）。"""
    from agent_eval.cli._common import observability_enabled, observability_flush
    from agent_eval.cli._stages import (
        _backfill_sut_identity,
        build_judge_context,
        evaluate_stage,
        execute_stage,
        resolve_eval_inputs,
        resolve_run_inputs,
    )
    from agent_eval.config.paths import paths
    from agent_eval.core.exceptions import AgentEvalError, GateConfigError
    from agent_eval.core.logging import (
        install_exec_event_handler,
        resolve_logging_level,
        setup_logging,
    )
    from agent_eval.llm.tracing import flush_traces
    from agent_eval.reporting.gate import normalize_gate
    from agent_eval.storage.package import generate_run_id

    def _emit(stage: PipelineStage, payload: dict[str, Any] | None = None) -> None:
        if progress is not None:
            progress(stage, payload or {})

    def _fail(stage: str, exc: BaseException, exit_code: int = 1, **extra: Any) -> PipelineOutcome:
        _emit(PipelineStage.ABORT)
        return PipelineOutcome(
            stage=stage,
            exit_code=exit_code,
            error=str(exc),
            error_type=type(exc).__name__,
            **extra,
        )

    setup_logging(level=resolve_logging_level(params.log_level))
    install_exec_event_handler(enabled=params.log_level in ("verbose", "debug"))
    strict = params.on_missing == "strict"

    # ── 阶段 0：门禁语法校验（语义校验——float 模式无 reward——在评估后
    # 由 evaluate_gate 抛 GateConfigError，同样映射退出码 1）──
    try:
        normalize_gate(params.gate)
    except GateConfigError as e:
        return _fail("gate_config", e)
    try:
        inputs = resolve_run_inputs(
            params.package,
            task_set=params.task_set,
            task_select=params.task,
            sut_config=params.sut_config,
            sut_name=params.sut_name,
        )
        # 无包时 --rule-set 须为路径（resolve_eval_inputs 的 BadParameter 语义）
        rule_set_path = resolve_eval_inputs(params.package, params.rule_set)
    except Exception as e:  # noqa: BLE001 — 与 CLI 现行一致的兜底映射
        return _fail("resolve", e)

    # 凭证保障在进度视图启动前（转轮会刷掉补录输入提示行）——交互经
    # credential_filler 钩子留在壳层；缺省 None 时由 execute_stage 内
    # preflight fail fast 兜底（落 execute 阶段）
    if credential_filler is not None:
        try:
            credential_filler(inputs.sut)
        except AgentEvalError as e:
            return _fail("credentials", e)

    ws_root = Path(params.output_dir) if params.output_dir else paths.default_workspace
    run_id = generate_run_id()
    run_dir = ws_root / "runs" / run_id
    task_count = len(inputs.task_set_model.tasks)
    _emit(
        PipelineStage.RESOLVE_INFO,
        {
            "task_set_path": inputs.task_set_path,
            "task_count": task_count,
            "package_ref": (inputs.resolved_pkg.manifest.ref if inputs.resolved_pkg else None),
            "sut_name": inputs.sut.name,
            "sut_channel": inputs.sut.channel,
            "sut_base_url": inputs.sut.base_url,
            "rule_set_path": rule_set_path,
            "run_id": run_id,
        },
    )

    # ── 阶段 1：执行（清单 mode=pipeline，崩溃可溯源）──
    try:
        _emit(PipelineStage.EXECUTE, {"task_count": task_count, "sut_name": inputs.sut.name})
        packages = execute_stage(
            inputs,
            run_id=run_id,
            workspace_root=ws_root,
            mode="pipeline",
            llm_role=params.llm_role,
            max_turns=params.max_turns,
            cancel_event=cancel_event,
        )
    except AgentEvalError as e:
        return _fail("execute", e, run_id=run_id, run_dir=str(run_dir))

    succeeded = sum(1 for p in packages if p.manifest.status == "success")
    _emit(
        PipelineStage.EXECUTE_DONE,
        {
            "succeeded": succeeded,
            "total": len(packages),
            "log_dir": f"{ws_root}/runs/{run_id}/agent_logs/",
            "packages": packages,
        },
    )
    # 协作取消（任务边界）：已完成产物与 run_manifest 已落盘，不进评估/上报
    if cancel_event is not None and cancel_event.is_set():
        return PipelineOutcome(
            stage="cancelled",
            exit_code=130,
            cancelled=True,
            run_id=run_id,
            run_dir=str(run_dir),
        )

    # ── 阶段 2：评估（复用同一 run_id 的 RunWorkspace；清单合并 run 绑定字段）──
    packages_root = run_dir / "packages"
    run_manifest_extra = {
        "package_ref": (inputs.resolved_pkg.manifest.ref if inputs.resolved_pkg else None),
        "task_set": str(inputs.task_set_path),
        "sut": {"name": inputs.sut.name, "base_url": inputs.sut.base_url},
        "llm_role": params.llm_role or "agent",
        "packages": [str(p.output_dir or p.manifest.package_id) for p in packages],
    }
    try:
        _emit(PipelineStage.EVALUATE)
        judge_ctx = build_judge_context(rule_set_path, strict=strict)
        scenario_pkg_dir = inputs.resolved_pkg.root if inputs.resolved_pkg else None
        result = evaluate_stage(
            packages_root,
            judge_ctx,
            run=(ws_root, run_id),
            project=params.project,
            no_cache=params.no_cache,
            mode="pipeline",
            scenario_package_dir=scenario_pkg_dir,
            manifest_extra=run_manifest_extra,
            gate=params.gate,
            report_formats=params.report_formats,
            package_id=(inputs.resolved_pkg.manifest.id if inputs.resolved_pkg else ""),
            max_concurrency=params.concurrency,
        )
        _emit(PipelineStage.FINALIZE)
        flush_traces()
        _emit(PipelineStage.SUMMARY, {"report": result.report})
        _backfill_sut_identity(result)
        enabled = observability_enabled(result, upload_override=params.upload)
        _emit(PipelineStage.UPLOAD_START, {"enabled": enabled})
        receipt = observability_flush(
            result, upload_override=params.upload, package_dir=str(packages_root)
        )
        _emit(PipelineStage.UPLOAD, {"receipt": receipt})
    except Exception as e:  # noqa: BLE001 — 与 CLI 现行一致的兜底映射
        return _fail("evaluate", e, run_id=run_id, run_dir=str(run_dir))

    _emit(PipelineStage.DONE, {"run_dir": run_dir})
    payload = _run_json_payload(
        run_id=run_id,
        mode="pipeline",
        inputs=inputs,
        packages=packages,
        run_dir=run_dir,
        # EvalResult 的指标真相在 .report（MetricsReport）——曾误写
        # result.metrics 致终态渲染 AttributeError
        metrics=dict(result.report.metrics),
        total_samples=result.report.total_samples,
    )
    # 质量门禁退出码（在报告落盘与平台上报之后判定，门禁失败不阻断上报）
    gate_info = getattr(result, "gate", None) or {}
    common = {
        "run_id": run_id,
        "run_dir": str(run_dir),
        "metrics": dict(result.report.metrics),
        "total_samples": result.report.total_samples,
        "gate": gate_info,
        "upload_receipt": receipt,
        "payload": payload,
        "result": result,
    }
    if gate_info.get("enabled") and not gate_info.get("passed", True):
        return PipelineOutcome(stage="gate", exit_code=3, **common)
    return PipelineOutcome(stage="done", exit_code=0, **common)
