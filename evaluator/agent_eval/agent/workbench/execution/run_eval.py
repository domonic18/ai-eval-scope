"""RunEvalTool — 评测执行（run_evaluation，执行域主工具）。

编排零复制：``pipeline_core``经 ``_spawn_pipeline_worker``
在独立 daemon 线程运行；本工具只做「门槛 → 装配 → 终态摘要」：

① ask_fn 为空 → refused（**执行确认永不被 --trust-agent 旁路的唯一实现点**：
   非交互环境没有确认通道，直接拒绝而非静默执行）
② busy 守卫（active_event 兼哨兵；worker 存活同判，残留令牌就地 reap）
③ 确认门槛：等价 CLI 命令（console/equiv 同源 argv）展示给用户二选一；
   拒绝 → declined，pipeline_core 从未被调用
④ 渲染桥挂起 + 取消令牌置位（busy 哨兵同源）
⑤ daemon worker(pipeline_core, progress=桥包装的共用渲染器, cancel_event,
   credential_filler=ask_fn 补录循环)；等待侧零 join
⑥ finally 复位 + 桥恢复（core 的 setup_logging 是进程全局突变，桥负责快照恢复）；
   KI/取消硬中断保留令牌作僵尸 worker 取消通道（下一轮入口 reap）
⑦ 紧凑摘要（指标不全文罗列，明细引 show_run）
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import contextlib
import threading
from typing import Any

from agent_eval.agent.workbench.execution.context import ExecContext
from agent_eval.cli.pipeline_core import PipelineOutcome, PipelineParams, pipeline_core

_CONFIRM = "确认执行"

# 等待侧取消后 set_result/set_exception 的终态报错：3.8–3.12 抛 CancelledError、
# 3.13+ 抛 InvalidStateError("CANCELLED")——双类兼容（实测 3.13 走 InvalidStateError）
_FUT_STATE_ERRORS = (
    concurrent.futures.CancelledError,
    concurrent.futures.InvalidStateError,
)


def _make_credential_filler(ctx: ExecContext) -> Any:
    """凭证补录钩子（复刻 CLI _fill_missing_credentials 语义，交 ask_fn）。

    在 worker 线程内同步执行：逐字段 asyncio.run 微型 loop（ask_fn 只做终端
    I/O 无线程亲和）；任一空输入 SUTAuthError 整体取消（不留半截状态）；
    一次落盘密钥区。复检由 execute_stage 内 preflight 兜底。
    """

    def filler(sut: Any) -> None:
        from agent_eval.core.exceptions import SUTAuthError
        from agent_eval.execution.auth.credentials import missing_credential_fields
        from agent_eval.execution.auth.secrets_store import load_secrets_file, save_secrets_file

        missing = missing_credential_fields(sut)
        if not missing:
            return
        ref = str(getattr(getattr(sut, "auth", None), "credential_ref", ""))
        values: dict[str, str] = {}
        for field in missing:
            answer = asyncio.run(
                ctx.ask_fn(
                    f"【录入 {ref} 的凭证字段 {field}】\n"
                    f"用途：执行评测须向被测系统 {sut.name} 发真实请求；"
                    "输入不回显、直存本机密钥区（0600）",
                    options=None,
                    secret=True,
                )
            )
            if not answer:
                raise SUTAuthError(
                    f"未输入 {ref}.{field}，已取消补录（可 secrets set 后重试，或让用户在交互终端执行）"
                )
            values[field] = answer
        secrets = load_secrets_file(None)
        secrets.setdefault(ref, {}).update(values)
        save_secrets_file(secrets, None)
        ctx.log("credential_filled", ref=ref, fields=sorted(values))

    return filler


def _spawn_pipeline_worker(
    params: PipelineParams,
    *,
    progress: Any,
    cancel: threading.Event,
    filler: Any,
) -> tuple[concurrent.futures.Future, threading.Thread]:
    """单飞 daemon worker：pipeline_core 跑独立守护线程，等待侧零 join。

    为何不用 ``asyncio.to_thread``：to_thread 落
    loop 默认线程池，KI 硬中断后 ``Runner.close`` 会 shutdown+join 该池（上限
    300s）——当前任务分钟级时终端冻结，用户连按 Ctrl+C 会击穿 asyncio.run 收尾
    的信号窗口，running-loop 线程态泄漏、会话报废。daemon worker 让 teardown
    无可 join：turn 即时收轮，worker 后台继续到任务边界收尾（cancelled 产物照常
    落盘），进程退出随解释器终止（与 CLI 硬中断同语义）。busy/协作中断经
    ``ctx.active_event`` 保留的令牌仍然可达（见 run_evaluation ⑥）。
    """

    fut: concurrent.futures.Future = concurrent.futures.Future()

    def _run() -> None:
        try:
            result = pipeline_core(
                params, progress=progress, cancel_event=cancel, credential_filler=filler
            )
        except BaseException as e:  # noqa: BLE001 — 原样过桥，等待侧映射终态
            with contextlib.suppress(*_FUT_STATE_ERRORS):
                fut.set_exception(e)  # 等待侧已取消 → 结果无人接，worker 就此收尾
        else:
            with contextlib.suppress(*_FUT_STATE_ERRORS):
                fut.set_result(result)

    thread = threading.Thread(target=_run, name="agent-eval-pipeline", daemon=True)
    thread.start()
    return fut, thread


class RunEvalTool:
    """工具：run_evaluation——确认门槛 + pipeline_core 装配 + 终态摘要。"""

    def __init__(self, ctx: ExecContext) -> None:
        self.ctx = ctx

    async def run_evaluation(
        self,
        package: str = "",
        task_set: str = "",
        task: str = "",
        sut_name: str = "",
        sut_config: str = "",
        rule_set: str = "",
        gate: str = "off",
        project: str = "",
        no_cache: bool = False,
        on_missing: str = "skip",
        log_level: str = "normal",
    ) -> dict[str, Any]:
        # ① 非交互拒绝（唯一旁路拒绝点）：确认是执行的前置语义，无确认通道即不执行
        if self.ctx.ask_fn is None:
            return {
                "status": "refused",
                "reason": "非交互环境（--yes/CI）不支持会话内执行评测——请在交互终端运行，或用等价 CLI 命令",
            }
        # ② busy 守卫：执行中（active_event）或上轮硬中断的 daemon worker 尚在
        #    后台收尾（worker_alive）都拒绝并发；worker 已退出的残留令牌就地 reap
        if self.ctx.active_event is not None and not self.ctx.worker_alive():
            self.ctx.active_event = None  # 上轮 KI 僵尸已退出——清账放行
        if self.ctx.active_event is not None or self.ctx.worker_alive():
            return {
                "status": "busy",
                "note": "已有评测在执行中（或上轮硬中断后仍在后台收尾），"
                "等待完成或 Ctrl+C 协作中断",
            }

        # ③ 确认门槛：等价命令展示 + 二选一（拒绝 → pipeline_core 从未被调用）
        from agent_eval.cli.console.equiv import pipeline_argv, render

        argv = pipeline_argv(
            package=package or None,
            task_set=task_set or None,
            task=task or None,
            sut_name=sut_name or None,
            sut_config=sut_config or None,
            rule_set=rule_set or None,
            gate=None if gate in ("", "off") else gate,
            project=project or None,
            no_cache=no_cache or None,
            on_missing=None if on_missing == "skip" else on_missing,
            log_level=None if log_level == "normal" else log_level,
        )
        answer = await self.ctx.ask_fn(
            f"将执行评测（等价命令，进度将直出本终端）：\n  {render(argv)}\n确认执行？",
            options=["确认执行", "取消"],
            secret=False,
        )
        if answer != _CONFIRM:
            self.ctx.log("run_evaluation", confirmed=False)
            return {"status": "declined", "equivalent_command": render(argv)}

        # ④⑤⑥ 装配 + worker 线程执行（finally 复位哨兵/恢复桥）
        from agent_eval.cli.console.pipeline_render import make_pipeline_renderer

        params = PipelineParams(
            package=package or None,
            task_set=task_set or None,
            task=task or None,
            sut_name=sut_name or None,
            sut_config=sut_config or None,
            rule_set=rule_set or None,
            gate=gate or "off",
            project=project or None,
            no_cache=no_cache,
            on_missing=on_missing,
            log_level=log_level,
        )
        renderer = make_pipeline_renderer(log_level)
        bridge = self.ctx.bridge
        progress = (
            bridge.pipeline_progress(renderer) if bridge is not None else renderer.on_progress
        )
        cancel = threading.Event()
        self.ctx.active_event = cancel
        if bridge is not None:
            bridge.suspend()
        outcome: PipelineOutcome | None = None
        failure: BaseException | None = None
        try:
            fut, worker = _spawn_pipeline_worker(
                params,
                progress=progress,
                cancel=cancel,
                filler=_make_credential_filler(self.ctx),
            )
            self.ctx.worker_thread = worker
            outcome = await asyncio.wrap_future(fut)
        except BaseException as e:  # noqa: BLE001 — 终态映射兜底（含 KI 透传宿主）
            failure = e
        finally:
            if failure is None or not isinstance(
                failure, (KeyboardInterrupt, asyncio.CancelledError)
            ):
                self.ctx.active_event = None  # 正常/内部失败：worker 已退出，令牌清账
            # KI/取消硬中断：保留令牌作僵尸 worker 的取消通道（busy 守卫与
            # interrupt_active 仍可达），由下次 run_evaluation 入口 reap
            if bridge is not None:
                bridge.resume()
        if failure is not None:
            self.ctx.log("run_evaluation", stage="internal", error=str(failure))
            if isinstance(failure, (KeyboardInterrupt, asyncio.CancelledError)):
                raise failure  # 宿主暂停语义（_attempt 捕获），非本工具终态
            return {
                "status": "failed",
                "stage": "internal",
                "error": str(failure),
                "error_type": type(failure).__name__,
            }
        assert outcome is not None
        return self._summarize(outcome)

    # ── 终态摘要（⑦）──────────────────────────────────────────

    def _summarize(self, outcome: PipelineOutcome) -> dict[str, Any]:
        self.ctx.log(
            "run_evaluation",
            stage=outcome.stage,
            exit_code=outcome.exit_code,
            run_id=outcome.run_id,
        )
        receipt = outcome.upload_receipt or {}
        uploaded = bool(receipt.get("enabled")) and not (
            receipt.get("error") or receipt.get("init_error")
        )
        platform_url = str(receipt.get("view_url") or "")
        report = getattr(outcome.result, "report", None) if outcome.result is not None else None
        breakdown = getattr(report, "failure_breakdown", None) if report is not None else None
        payload = outcome.payload or {}
        tasks = {
            "total": payload.get("total"),
            "succeeded": payload.get("succeeded"),
            "failed": (payload.get("total", 0) or 0) - (payload.get("succeeded", 0) or 0)
            if payload
            else None,
        }
        common = {
            "run_id": outcome.run_id,
            "run_dir": outcome.run_dir,
            "tasks": tasks,
            "metrics": outcome.metrics,
            "total_samples": outcome.total_samples,
            "failure_breakdown": breakdown,
            "gate": outcome.gate,
            "uploaded": uploaded,
            "platform_url": platform_url,
        }
        if outcome.cancelled:
            return {
                "status": "cancelled",
                **common,
                "note": "协作中断——已完成任务的产物与运行清单已落盘，可溯源/续跑",
                "next_step": f"看部分结果: show_run(run_id='{outcome.run_id}')；重跑直接再调 run_evaluation",
            }
        if outcome.stage == "gate":
            return {
                "status": "gate_failed",
                "exit_code": 3,
                **common,
                "note": "质量门禁未达标（报告已生成、上报未阻断）",
                "next_step": f"失败归因: show_run(run_id='{outcome.run_id}')；调包后重跑再验",
            }
        if outcome.stage != "done":
            return {
                "status": "failed",
                "stage": outcome.stage,
                "error": outcome.error,
                "error_type": outcome.error_type,
                "run_id": outcome.run_id,
                "run_dir": outcome.run_dir,
                "next_step": "按 stage 定位：resolve/credentials=配置与凭证；execute=被测系统；evaluate=评估链",
            }
        next_step = (
            f"平台报告: {platform_url}；失败明细 show_run(run_id='{outcome.run_id}')"
            if uploaded
            else (
                "已入离线队列（凭据恢复后自动重放）"
                if receipt.get("enabled")
                else f"推送平台: upload_run(run_id='{outcome.run_id}')；失败明细: show_run(run_id='{outcome.run_id}')"
            )
        )
        return {"status": "done", **common, "next_step": next_step}
