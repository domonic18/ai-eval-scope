"""评测数据集下载与管理。

提供从 HuggingFace / ModelScope 下载公开评测数据集的能力，默认落盘到
``workspace/datasets/{name}/``，每次下载写入 ``_dataset_manifest.json`` 以便追溯。

入口：``DatasetManager.download()``，由 CLI ``agent-eval dataset download`` 调用。
设计详见 docs/arch/10数据集下载设计.md。
"""

from agent_eval.core.types import DatasetSource
from agent_eval.datasets.manager import DatasetManager
from agent_eval.datasets.registry import DatasetEntry, list_datasets, lookup

__all__ = [
    "DatasetManager",
    "DatasetEntry",
    "DatasetSource",
    "list_datasets",
    "lookup",
]
