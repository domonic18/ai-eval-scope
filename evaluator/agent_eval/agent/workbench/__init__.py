"""评测工作台域：会话机 WorkbenchAgent 与包工程/SUT 探测工具面。

CLI 宿主经本门面取类型与工具面；需 monkeypatch 的符号（``run_turn`` /
``WorkbenchAgent``）一律从定义模块 ``agent_eval.agent.workbench.agent``
导入——门面是导入时绑定，patch 定义模块属性不影响门面已绑定的名字。
"""

from agent_eval.agent.workbench.agent import (
    WorkbenchAgent,
    WorkbenchAgentConfig,
    run_turn,
)
from agent_eval.agent.workbench.sut_probe import SUTProbeToolServer
from agent_eval.agent.workbench.tools import PackageToolServer
from agent_eval.agent.workbench.types import TurnResult

__all__ = [
    "PackageToolServer",
    "SUTProbeToolServer",
    "TurnResult",
    "WorkbenchAgent",
    "WorkbenchAgentConfig",
    "run_turn",
]
