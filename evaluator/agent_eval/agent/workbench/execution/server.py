"""ExecutionToolServer — 评测执行域组装壳（Sprint 14b，arch/15 v4.12 §6.10）。

与 SUTProbeToolServer 同形态的组合薄壳：ExecContext（共享状态）+ 每域一个
工具类，本壳只做装配与委托（签名逐字复制供 StructuredTool schema 推导）。
agent→cli 依赖全部方法体内惰性导入（workbench 组织约定，包初始化期无环）。

执行确认是硬门槛：ask_fn 为空即拒绝（run_eval ①），``--trust-agent`` 不旁路。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_eval.agent.core.tools import ToolExporterMixin, ToolSpec
from agent_eval.agent.workbench.execution.browse import BrowseTool
from agent_eval.agent.workbench.execution.context import ExecContext
from agent_eval.agent.workbench.execution.run_eval import RunEvalTool
from agent_eval.agent.workbench.execution.specs import EXEC_TOOL_SPECS
from agent_eval.agent.workbench.execution.targets import TargetsTool
from agent_eval.agent.workbench.execution.upload import UploadTool


class ExecutionToolServer(ToolExporterMixin):
    """会话内评测执行工具面：确认门槛 + pipeline_core 编排复用 + 只读浏览。"""

    TOOL_SPECS: list[ToolSpec] = EXEC_TOOL_SPECS

    def __init__(
        self,
        *,
        ask_fn: Any = None,  # async (question, *, options, secret) -> str | None
        render_bridge: Any = None,  # ExecutionRenderBridge（cli/console/exec_bridge，宿主注入）
        workspace_root: Path | None = None,
        log_path: Path | None = None,
    ) -> None:
        self._ctx = ExecContext(
            ask_fn=ask_fn,
            bridge=render_bridge,
            workspace_root=workspace_root,
            log_path=log_path,
        )
        self._targets = TargetsTool(self._ctx)
        self._run_eval = RunEvalTool(self._ctx)
        self._browse = BrowseTool(self._ctx)
        self._upload = UploadTool(self._ctx)

    # ── 工具委托（签名逐字复制：StructuredTool 据此推导参数 Schema）──

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
        """执行评测流水线（确认门槛 + 终端直出进度 + 紧凑摘要）。"""
        return await self._run_eval.run_evaluation(
            package,
            task_set=task_set,
            task=task,
            sut_name=sut_name,
            sut_config=sut_config,
            rule_set=rule_set,
            gate=gate,
            project=project,
            no_cache=no_cache,
            on_missing=on_missing,
            log_level=log_level,
        )

    async def list_eval_targets(self, source: str = "") -> dict[str, Any]:
        """列出可评测对象（三源场景包 + 包内任务集/SUT/规则集清单）。"""
        return await self._targets.list_eval_targets(source)

    async def list_runs(self, limit: int = 10) -> dict[str, Any]:
        """列出本地评测运行（新→旧）。"""
        return await self._browse.list_runs(limit)

    async def show_run(self, run_id: str) -> dict[str, Any]:
        """查看单次运行详情（指标摘要 + 失败归因）。"""
        return await self._browse.show_run(run_id)

    async def upload_run(self, run_id: str, project: str = "") -> dict[str, Any]:
        """把已完成的运行推送到可观测平台（补传/重放）。"""
        return await self._upload.upload_run(run_id, project)

    # ── 设施委托（宿主生命周期挂钩）────────────────────────────

    def new_turn(self) -> None:
        """每轮 REPL 开始时由 WorkbenchAgent 调用（轮次标记，见 ExecContext）。"""
        self._ctx.new_turn()

    def interrupt_active_execution(self) -> bool:
        """协作中断活跃执行（宿主 SIGINT 首按落点）；无活跃执行返回 False。"""
        return self._ctx.interrupt_active()

    @property
    def ctx(self) -> ExecContext:
        """共享状态直读（测试/宿主装配用）。"""
        return self._ctx
