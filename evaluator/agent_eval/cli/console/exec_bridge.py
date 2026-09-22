"""ExecutionRenderBridge — 会话内执行评测的终端与日志状态桥。

WorkbenchAgent 会话（流式 emitter 单写者）与 pipeline_core worker 线程
（PipelineRenderer 直出）共享同一终端——桥解决两件事：

- **写者仲裁**：执行期挂起流式 emitter（gated_emit 丢弃 LLM 事件行），
  worker 的管线渲染成为唯一写者；取消时永久封缄（sealed），与主流程
  失联的僵尸 worker 线程从此静音（``PipelineRenderer.seal`` 同机理）。
- **日志档位快照/恢复**：pipeline_core 的 ``setup_logging`` 是进程全局
  突变（root handlers 清空重装 + 执行事件日志器重置）——Agent 会话的
  日志档位（14a 四档）必须在其后复原，否则档位泄漏到会话后续所有轮。

状态机：normal →（suspend）→ suspended →（resume）→ normal；任意态
→（cancel）→ sealed（永久，仅恢复日志不重开渲染门）。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from agent_eval.core.exec_events import EXEC_EVENT_LOGGER

__all__ = ["ExecutionRenderBridge"]

# 流式事件形态：dict（token/tool_start/tool_end/phase，见 agent_stream）
StreamEmit = Callable[[dict[str, Any]], None]
StreamFinish = Callable[[], None]


class ExecutionRenderBridge:
    """流式 emitter 的门控包装 + 日志档位快照/恢复（宿主构造注入）。"""

    def __init__(self, emit: StreamEmit | None, finish: StreamFinish | None = None) -> None:
        self._emit = emit
        self._finish = finish
        self._suspended = False
        self._sealed = False
        self._renderer: Any = None
        self._log_level: str | None = None
        self._exec_events_visible = False

    # ── 流式 emitter 门控（run_turn 的 on_event 走这里）──────────

    def gated_emit(self, event: dict[str, Any]) -> None:
        """挂起/封缄期丢弃（worker 渲染时宿主阻塞在 tool future，本为零事件；
        中断后 zombie 兜底）；normal 态直通。"""
        if self._suspended or self._sealed or self._emit is None:
            return
        self._emit(event)

    # ── 生命周期（run_evaluation 调用；host SIGINT 经 ctx.interrupt_active）──

    def suspend(self) -> None:
        """执行前挂起：收未闭合行 + 快照日志档位。"""
        if self._sealed:
            return
        if self._finish is not None:
            self._finish()
        self._snapshot_logging()
        self._suspended = True

    def resume(self) -> None:
        """执行后恢复：日志档位复原（渲染门重开）。"""
        if self._sealed:
            return
        self._suspended = False
        self._restore_logging()

    def cancel(self) -> None:
        """协作中断：永久封缄（保持挂起）+ 日志复原 + 渲染器 seal。"""
        if self._sealed:
            return
        self._sealed = True
        self._suspended = False
        if self._renderer is not None:
            self._renderer.seal()
        self._restore_logging()

    def pipeline_progress(self, renderer: Any) -> Callable[[Any, Any], None]:
        """包装管线渲染回调：封缄即丢弃（替代裸 renderer.on_progress 传 core）。

        注意挂起不作用于这里——suspend 只门控流式 emitter（LLM 事件行），
        执行期管线渲染是终端唯一写者、必须直通（「与 CLI 同命令逐字节同源」）。
        """
        self._renderer = renderer

        def _progress(stage: Any, payload: Any) -> None:
            if self._sealed:
                return
            renderer.on_progress(stage, payload)

        return _progress

    # ── 日志档位快照/恢复（core/logging 公开 API）────────────────

    def _snapshot_logging(self) -> None:
        self._log_level = logging.getLevelName(logging.getLogger().level)
        self._exec_events_visible = bool(logging.getLogger(EXEC_EVENT_LOGGER).handlers)

    def _restore_logging(self) -> None:
        if self._log_level is None:
            return
        from agent_eval.core.logging import install_exec_event_handler, setup_logging

        setup_logging(level=self._log_level)
        install_exec_event_handler(enabled=self._exec_events_visible)
