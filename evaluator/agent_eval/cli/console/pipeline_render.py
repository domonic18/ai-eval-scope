"""管线进度渲染器。

``PipelineRenderer`` 消费 ``pipeline_core`` 的 progress 事件，维护阶段进度视图
（``stage_progress``）生命周期与信息行/任务表/摘要/上报回执渲染——CLI 壳与
WorkbenchAgent 执行域共用同一实例，「Agent 会话内执行与 CLI 同命令逐字节同源」
的落点。``seal()`` 渲染门永久关闭：Agent 域协作中断后与主流程失联的 worker
线程从此不再写终端（僵尸线程静音）。
"""

from __future__ import annotations

from typing import Any

from agent_eval.cli._common import _print_summary, _render_upload_receipt, rprint
from agent_eval.cli.console.render import print_task_table, progress_mode, stage_progress
from agent_eval.cli.pipeline_core import PipelineStage

__all__ = ["PipelineRenderer", "make_pipeline_renderer"]


class PipelineRenderer:
    """progress 事件 → 终端渲染（无状态机外泄；close/seal 幂等）。"""

    def __init__(self, *, log_level: str = "normal") -> None:
        self._mode = progress_mode(log_level)
        self._stage_view: stage_progress | None = None
        self._sealed = False

    def on_progress(self, stage: PipelineStage, payload: dict[str, Any]) -> None:
        if self._sealed:
            return
        handler = {
            PipelineStage.RESOLVE_INFO: self._resolve_info,
            PipelineStage.EXECUTE: self._execute,
            PipelineStage.EXECUTE_DONE: self._execute_done,
            PipelineStage.EVALUATE: self._evaluate,
            PipelineStage.FINALIZE: self._finalize,
            PipelineStage.SUMMARY: self._summary,
            PipelineStage.UPLOAD_START: self._upload_start,
            PipelineStage.UPLOAD: self._upload,
            PipelineStage.DONE: self._done,
            PipelineStage.ABORT: self._abort,
        }[stage]
        handler(payload)

    def close(self) -> None:
        """幂等关进度视图（异常/中断路径兜底）。"""
        self._close_view()

    def seal(self) -> None:
        """渲染门永久关闭：close 后 on_progress 变 no-op（僵尸线程静音）。"""
        self.close()
        self._sealed = True

    # ── 事件处理（文案与 CLI 现行输出逐字一致）──

    def _resolve_info(self, p: dict[str, Any]) -> None:
        suffix = f"（包 {p['package_ref']}）" if p.get("package_ref") else ""
        rprint(f"[blue]任务集:[/blue] {p['task_set_path']}（{p['task_count']} 个任务）{suffix}")
        rprint(
            f"[blue]被测系统:[/blue] {p['sut_name']}"
            f"（channel={p['sut_channel']}, base_url={p['sut_base_url']}）"
        )
        rprint(f"[blue]规则集:[/blue] {p['rule_set_path']}")
        rprint(f"[blue]运行 ID:[/blue] {p['run_id']}（一体化流水线，mode=pipeline）")

    def _execute(self, p: dict[str, Any]) -> None:
        self._open_view()
        assert self._stage_view is not None
        self._stage_view.advance(f"执行 {p['task_count']} 个任务（SUT: {p['sut_name']}）")

    def _execute_done(self, p: dict[str, Any]) -> None:
        self._close_view()
        rprint(
            f"[green]执行完成:[/green] {p['succeeded']}/{p['total']} 成功；"
            f"结构化日志: {p['log_dir']}"
        )
        print_task_table(p["packages"])

    def _evaluate(self, p: dict[str, Any]) -> None:
        self._open_view()
        assert self._stage_view is not None
        self._stage_view.advance("评估（Rule-based + LLM Judge）")

    def _finalize(self, p: dict[str, Any]) -> None:
        if self._stage_view is not None:
            self._stage_view.advance("上报 / 收尾")

    def _summary(self, p: dict[str, Any]) -> None:
        _print_summary(p["report"])
        rprint("[green]✅ 评估完成[/green] — 结果已保存至 workspace")

    def _upload_start(self, p: dict[str, Any]) -> None:
        if p.get("enabled"):
            rprint("[blue]可观测平台:[/blue] 推送结果中…")

    def _upload(self, p: dict[str, Any]) -> None:
        _render_upload_receipt(p["receipt"])

    def _done(self, p: dict[str, Any]) -> None:
        self._close_view()
        rprint(f"[green]✅ 流水线完成[/green] — {p['run_dir']}")

    def _abort(self, p: dict[str, Any]) -> None:
        self._close_view()

    # ── 进度视图生命周期 ──

    def _open_view(self) -> None:
        if self._stage_view is None:
            self._stage_view = stage_progress(mode=self._mode)
            self._stage_view.__enter__()

    def _close_view(self) -> None:
        if self._stage_view is not None:
            self._stage_view.__exit__(None, None, None)
            self._stage_view = None


def make_pipeline_renderer(log_level: str = "normal") -> PipelineRenderer:
    """渲染器工厂（CLI 壳与 Agent 执行域同源入口）。"""
    return PipelineRenderer(log_level=log_level)
