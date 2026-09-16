"""rich 渲染 — 阶段进度视图与任务状态表（F-C-EXEC-03，arch/15 §3.2 render）。

进度视图为**阶段级**（解析 → 执行 → 评估 → 收尾）：execute_stage 内部是一次性
``agent.run_task_set()``，逐任务实时态需 ExecutionAgent 回调改造（Sprint 11+ 经
SessionLogCallback 接入），当前以「执行中 spinner + 完成态逐任务表」落地。
``--output-format json`` 下进度视图禁用（进度即人读输出）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from rich.progress import Progress

from rich.progress import TaskID

from agent_eval.cli._common import Table, rprint

__all__ = ["print_task_table", "stage_progress"]


class stage_progress:  # noqa: N801 — 用作上下文管理器
    """阶段进度视图（上下文管理器）：``with stage_progress() as sp: sp.advance("执行")``。

    非 TTY / JSON 模式下退化为 stderr 单行阶段提示，不影响管道与 CI。
    """

    def __init__(self, *, enabled: bool = True) -> None:
        self._enabled = enabled
        self._progress: Progress | None = None
        self._task_id: TaskID | None = None
        self._fallback_label = ""

    def __enter__(self) -> stage_progress:
        if not self._enabled:
            return self
        import sys

        from rich.console import Console
        from rich.progress import Progress, SpinnerColumn, TextColumn

        # 进度行固定走 stderr：text 模式不污染 stdout 管道，json 模式天然分流
        self._progress = Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=Console(file=sys.stderr),
            transient=True,
        )
        self._progress.__enter__()
        self._task_id = self._progress.add_task("准备…", total=None)
        return self

    def advance(self, label: str) -> None:
        """切换当前阶段描述。"""
        if self._progress is not None and self._task_id is not None:
            self._progress.update(self._task_id, description=f"[blue]{label}[/blue]")
        elif self._enabled:
            import sys

            print(f"[stage] {label}", file=sys.stderr)
            self._fallback_label = label

    @property
    def last_label(self) -> str:
        return self._fallback_label

    def __exit__(self, *exc: object) -> None:
        if self._progress is not None:
            self._progress.__exit__(
                exc[0] if exc else None,  # type: ignore[arg-type]
                exc[1] if len(exc) > 1 else None,  # type: ignore[arg-type]
                exc[2] if len(exc) > 2 else None,  # type: ignore[arg-type]
            )
            self._progress = None


def print_task_table(packages: list) -> None:  # noqa: ANN001 — ExecutionPackage 列表
    """执行完成后的逐任务状态表（进度视图回落完整摘要的一半，另一半为指标表）。"""
    if not packages:
        return
    table = Table(title=f"任务结果（{len(packages)}）")
    table.add_column("task_id", style="cyan")
    table.add_column("状态")
    table.add_column("输出目录")
    for p in packages:
        status = p.manifest.status
        color = "green" if status == "success" else "red"
        table.add_row(
            p.manifest.task_id,
            f"[{color}]{status}[/{color}]",
            str(p.output_dir or p.manifest.package_id),
        )
    rprint(table)
