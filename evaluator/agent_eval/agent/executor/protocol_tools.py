"""Agent Protocol 语义工具面。

取代手搓 HTTP 请求：agent_run / agent_run_stream / create_thread /
run_on_thread / read_thread_state / answer_sut_questions / cancel_run /
get_agent_info / download_sut_file 九个语义工具，封装
AgentProtocolChannel 暴露给 DeepAgents 显式绑定（ToolExporterMixin）。

组合结构（按职责拆分，均 <300 行）：
- ``protocol_shared``：常量 / 守卫装饰器 / 结果限幅纯函数
- ``protocol_specs``：TOOL_SPECS 规格（Agent 侧工具文档）
- ``protocol_state``：任务级状态 + 预算闸门 + 简报注入 + 终局刷新
- ``protocol_tools_run``：执行与取证工具（dispatch / 线程 / 只读仲裁）
- ``protocol_tools_sut``：反问应答 / 取消 / 能力发现 / 产物下载
- 本模块：组合主体（``__init__`` 状态建立）
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_eval.agent.core.tools import ToolExporterMixin, ToolSpec
from agent_eval.agent.executor.briefing import SutStateTracker
from agent_eval.agent.executor.ledger import ResourceLedger
from agent_eval.agent.executor.protocol_shared import bounded_result, tool_guard
from agent_eval.agent.executor.protocol_specs import TOOL_SPECS as _PROTOCOL_TOOL_SPECS
from agent_eval.agent.executor.protocol_tools_run import ProtocolRunToolsMixin
from agent_eval.agent.executor.protocol_tools_sut import ProtocolSutToolsMixin
from agent_eval.execution.channels.agent_protocol import AgentProtocolChannel

__all__ = ["AgentProtocolToolServer", "bounded_result", "tool_guard"]


class AgentProtocolToolServer(
    ProtocolRunToolsMixin,
    ProtocolSutToolsMixin,
    ToolExporterMixin,
):
    """Agent Protocol 语义工具注册表，绑定一个 AgentProtocolChannel。"""

    # 与基类同形态（非 ClassVar）：ClassVar 遮蔽实例变量声明会被 mypy 拒绝
    TOOL_SPECS: list[ToolSpec] = _PROTOCOL_TOOL_SPECS
    discipline_key = "agent_protocol"  # 通道专属纪律段（execution_agent_prompts.yaml）

    def __init__(
        self,
        channel: AgentProtocolChannel,
        *,
        default_metadata: dict[str, Any] | None = None,
        workspace_dir: str | Path | None = None,
    ) -> None:
        """初始化工具注册表。

        Args:
            channel: Agent Protocol 通道实例。
            default_metadata: 附加到每次 run 的元数据（如 eval_run_id/sut_name，
                便于被测系统侧审计与限流豁免协商）。
            workspace_dir: 产物下载落盘根（download_sut_file 写
                {workspace_dir}/{task_id}/output/）；缺省 None，由 ExecutionAgent
                逐 run 注入包根——目的地是执行器基础设施，不由 LLM 决定。
        """
        self.channel = channel
        self.default_metadata = default_metadata or {}
        self.workspace_dir: Path | None = Path(workspace_dir) if workspace_dir else None
        # 最近一次 SUT run 摘要（ExecutionPackage trace 回填 SUT 回答文本用）
        self.last_run: dict[str, Any] | None = None
        # 本任务 SUT 调用超时留证（reset_task_state 逐任务清账）
        self._timeout_errors: list[str] = []
        # 交互预算账本——缺省 None=fail-closed（未注入即拒绝，
        # 见 _budget）；ExecutionAgent 逐任务注入新实例（账本随任务生灭，
        # reset_task_state 不清它——换新即清零）
        self.ledger: ResourceLedger | None = None
        # SUT 状态观察时间线——reset_task_state
        # 逐任务换新，与账本同节奏
        self._tracker = SutStateTracker()
