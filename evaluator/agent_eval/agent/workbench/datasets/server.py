"""DatasetToolServer — 数据集域组装壳。

与 ExecutionToolServer 同形态的组合薄壳：DatasetContext（共享状态）+ 每域
一个工具类，本壳只做装配与委托（签名逐字复制供 StructuredTool schema 推导）。
agent→cli 依赖全部方法体内惰性导入（workbench 组织约定，包初始化期无环）。

下载确认是硬门槛：ask_fn 为空即拒绝（tools ①），``--trust-agent`` 不旁路。
无轮内状态与预算（确认即预算），故无 new_turn/interrupt 挂钩。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_eval.agent.core.tools import ToolExporterMixin, ToolSpec
from agent_eval.agent.workbench.datasets.specs import DATASET_TOOL_SPECS
from agent_eval.agent.workbench.datasets.tools import DatasetContext, DownloadTool, ListDatasetsTool


class DatasetToolServer(ToolExporterMixin):
    """会话内数据集工具面：索引/本地状态只读 + 确认门槛下载（受控出网）。"""

    TOOL_SPECS: list[ToolSpec] = DATASET_TOOL_SPECS

    def __init__(
        self,
        *,
        ask_fn: Any = None,  # async (question, *, options, secret) -> str | None
        workspace_root: Path | None = None,
        log_path: Path | None = None,
    ) -> None:
        self._ctx = DatasetContext(
            ask_fn=ask_fn,
            workspace_root=workspace_root,
            log_path=log_path,
        )
        self._list = ListDatasetsTool(self._ctx)
        self._download = DownloadTool(self._ctx)

    # ── 工具委托（签名逐字复制：StructuredTool 据此推导参数 Schema）──

    async def list_datasets(self) -> dict[str, Any]:
        """列出评测数据集（索引清单 + 本地已下载状态）。"""
        return await self._list.list_datasets()

    async def download_dataset(
        self,
        name: str,
        source: str = "",
        revision: str = "",
        force: bool = False,
    ) -> dict[str, Any]:
        """下载数据集到 workspace/datasets/（确认门槛 + 受控出网单出口）。"""
        return await self._download.download_dataset(
            name,
            source=source,
            revision=revision,
            force=force,
        )

    # ── 设施委托（宿主生命周期挂钩）────────────────────────────

    @property
    def ctx(self) -> DatasetContext:
        """共享状态直读（测试/宿主装配用）。"""
        return self._ctx
