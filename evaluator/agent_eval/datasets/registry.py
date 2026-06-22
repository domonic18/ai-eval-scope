"""数据集注册表 — 从随包 yaml 索引加载评测数据集的来源元数据。

索引文件：``agent_eval/assets/datasets/dataset_index.yaml``
移植自 OpenCompass（``dataset-index.yml`` 元数据 + ``DATASETS_MAPPING`` 下载地址）。
**维护数据集地址只需编辑该 yaml，无需改代码**——registry 首次访问时加载并校验。
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from agent_eval.config.loader import ConfigLoader, get_schema_path
from agent_eval.config.paths import paths
from agent_eval.core.logging import get_logger

logger = get_logger(__name__)

_INDEX_PATH = paths.assets_dir / "datasets" / "dataset_index.yaml"


@dataclass(frozen=True)
class DatasetEntry:
    """单条数据集的来源元数据。"""

    id: str  # 唯一标识，如 "ceval"
    name: str  # 展示名，如 "C-Eval"
    hf_id: str | None = None  # HuggingFace repo_id
    ms_id: str | None = None  # ModelScope dataset_id
    description: str = ""
    default_source: str = "auto"
    category: str = ""
    paper: str = ""

    def get_id(self, source: str) -> str | None:
        """按归一化后的 source（"huggingface" / "modelscope"）返回对应源的仓库 id。"""
        if source == "huggingface":
            return self.hf_id
        if source == "modelscope":
            return self.ms_id
        return None


@lru_cache(maxsize=1)
def _load_index() -> dict[str, DatasetEntry]:
    """加载并校验数据集索引 yaml，构建 id → DatasetEntry 映射。"""
    schema_path = get_schema_path("dataset_index_schema.json")
    data = ConfigLoader.load_and_validate(_INDEX_PATH, schema_path)
    result: dict[str, DatasetEntry] = {}
    for item in data.get("datasets", []):
        sources = item.get("sources") or {}
        entry = DatasetEntry(
            id=item["id"],
            name=item.get("name") or item["id"],
            hf_id=sources.get("hf_id"),
            ms_id=sources.get("ms_id"),
            description=item.get("description", ""),
            default_source=item.get("default_source", "auto"),
            category=item.get("category", ""),
            paper=item.get("paper", ""),
        )
        result[entry.id] = entry
    logger.debug("dataset.registry.loaded", count=len(result))
    return result


def lookup(dataset_id: str) -> DatasetEntry | None:
    """按 id 查注册表，未命中返回 None。"""
    return _load_index().get(dataset_id)


def list_datasets() -> dict[str, DatasetEntry]:
    """返回全部注册数据集（id → DatasetEntry 的副本）。"""
    return dict(_load_index())
