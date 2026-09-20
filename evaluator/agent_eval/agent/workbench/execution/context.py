"""ExecContext — 执行域共享状态（Sprint 14b，arch/15 v4.12 §6.10）。

与 ProbeContext 同构的最小上下文：ask_fn 交互桥 / render_bridge（None 可
降级）/ active_event（活跃执行的取消令牌兼 busy 哨兵）/ workspace_root /
log_path（jsonl 事件账本，格式同 ProbeContext.log）。

生命周期约定：
- ``active_event`` 仅由 run_evaluation ④ 置位、⑥ finally 复位——它是 busy
  哨兵（非 None = 有执行在 worker 线程），不随 REPL 换轮复位（new_turn 不
  触碰；执行期 REPL 阻塞在 tool future 上，不存在并发轮）。
- ``interrupt_active()`` 是宿主 SIGINT 首按的落点：置位令牌 + 封缄渲染桥
  （失联 worker 线程静音）+ 日志留痕。
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any


class ExecContext:
    """执行域共享状态（状态全公开名，宿主/测试直接读写）。"""

    def __init__(
        self,
        *,
        ask_fn: Any = None,  # async (question, *, options, secret) -> str | None
        bridge: Any = None,  # ExecutionRenderBridge（None=无桥降级，直渲染）
        workspace_root: Path | None = None,
        log_path: Path | None = None,
    ) -> None:
        self.ask_fn = ask_fn
        self.bridge = bridge
        self.active_event: threading.Event | None = None
        self.workspace_root = workspace_root
        self.log_path = log_path

    def new_turn(self) -> None:
        """每轮 REPL 开始钩子（与 probe.new_turn 对称）。

        执行无轮内预算、active_event 生命周期归 run_evaluation——此处仅留
        轮次日志标记，不复位任何状态（见模块 docstring 生命周期约定）。
        """
        self.log("turn_start")

    def interrupt_active(self) -> bool:
        """协作中断当前活跃执行（宿主 SIGINT 首按落点）；无活跃执行返回 False。"""
        if self.active_event is None:
            return False
        self.active_event.set()
        if self.bridge is not None:
            self.bridge.cancel()  # 渲染门永久封缄：失联 worker 线程静音
        self.log("interrupt", active=True)
        return True

    def log(self, tool: str, **payload: Any) -> None:
        """jsonl 事件账本（格式同 ProbeContext.log；log_path 为空则 no-op）。"""
        if self.log_path is None:
            return
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        entry = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "tool": tool, **payload}
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
