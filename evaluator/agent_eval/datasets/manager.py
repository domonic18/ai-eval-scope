"""DatasetManager — 下载编排：解析 → 选源 → 下载 → 落盘 → 写 manifest。

由 CLI ``agent-eval dataset download`` 调用。源切换优先级：
``--source`` 参数 > ``AGENT_EVAL_DATASET_SOURCE`` 环境变量 > 注册表 default_source。
"""

from __future__ import annotations

import json
import os
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path

from agent_eval.config.paths import paths
from agent_eval.core.exceptions import DatasetError, DatasetNotFoundError
from agent_eval.core.logging import get_logger

logger = get_logger(__name__)

# 源别名归一化表
_SOURCE_ALIASES = {
    "hf": "huggingface",
    "huggingface": "huggingface",
    "ms": "modelscope",
    "modelscope": "modelscope",
}

# 目录名安全化：仅保留字母数字、点、下划线、短横
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]")


def _normalize_source(source: str) -> str:
    """归一化源别名为 'huggingface' / 'modelscope'。"""
    key = source.strip().lower()
    if key not in _SOURCE_ALIASES:
        raise DatasetError(
            f"不支持的下载源: {source}（支持 huggingface/hf 或 modelscope/ms）"
        )
    return _SOURCE_ALIASES[key]


class DatasetManager:
    """数据集下载编排器。"""

    def download(
        self,
        name: str,
        source: str | None = None,
        output: Path | None = None,
        revision: str | None = None,
        token: str | None = None,
        force: bool = False,
    ) -> Path:
        """下载单个数据集，返回落盘目录。

        Args:
            name: 预置名（如 ``ceval``）或完整 repo id（如 ``opencompass/gsm8k``）。
            source: 下载源；None 时按环境变量/默认值解析。
            output: 落盘目录；None 时为 ``workspace/datasets/{name}``。
            revision: 版本标识。
            token: 访问 token。
            force: 目标目录已存在时强制重新下载。

        Raises:
            DatasetNotFoundError: 数据集在所选源上未提供 id。
            DatasetError: 源不支持等。
        """
        # 延迟导入避免顶层循环（__init__ re-export manager）
        from agent_eval.datasets.downloader import get_downloader
        from agent_eval.datasets.registry import DatasetEntry, lookup

        # 1. 解析 entry（注册表命中 / 视为完整 repo id）
        entry = lookup(name)
        if entry is None:
            entry = DatasetEntry(
                id=name, name=name, hf_id=name, ms_id=name, description="(用户指定 repo id)"
            )

        # 2. 解析 source
        resolved_source = self._resolve_source(source, entry)

        # 3. 取对应源 id
        repo_id = entry.get_id(resolved_source)
        if not repo_id:
            raise DatasetNotFoundError(
                f"数据集 '{name}' 在 {resolved_source} 源上未提供 id"
            )

        # 4. 解析目标目录
        target = self._resolve_target(name, output)

        # 5. 已存在则跳过（除非 force）
        if target.exists() and any(target.iterdir()):
            if force:
                shutil.rmtree(target)
            else:
                logger.info(
                    "dataset.exists", name=name, target=str(target)
                )
                return target

        # 6. 下载
        logger.info(
            "dataset.download.start",
            name=name,
            source=resolved_source,
            repo_id=repo_id,
            target=str(target),
        )
        downloader = get_downloader(resolved_source)
        downloader.download(repo_id, target, revision=revision, token=token)

        # 7. 写 manifest
        self._write_manifest(target, entry, resolved_source, repo_id, revision)
        logger.info("dataset.download.done", name=name, target=str(target))
        return target

    def _resolve_source(self, source: str | None, entry) -> str:
        if source:
            return _normalize_source(source)
        env = os.environ.get("AGENT_EVAL_DATASET_SOURCE")
        if env:
            return _normalize_source(env)
        ds = entry.default_source
        if ds == "auto":
            # 国内默认走 ModelScope，ms_id 缺失则退 HuggingFace
            return "modelscope" if entry.ms_id else "huggingface"
        return _normalize_source(ds)

    def _resolve_target(self, name: str, output: Path | None) -> Path:
        if output:
            return Path(output)
        # repo id 含命名空间（如 opencompass/ceval），取末段做目录名并安全化
        leaf = name.rsplit("/", 1)[-1]
        safe = _SAFE_NAME.sub("_", leaf)
        return paths.default_workspace / "datasets" / safe

    def _write_manifest(
        self,
        target: Path,
        entry,
        source: str,
        repo_id: str,
        revision: str | None,
    ) -> None:
        manifest = {
            "id": entry.id,
            "name": entry.name,
            "source": source,
            "repo_id": repo_id,
            "revision": revision,
            "category": entry.category,
            "paper": entry.paper,
            "description": entry.description,
            "downloaded_at": datetime.now(UTC).isoformat(),
        }
        (target / "_dataset_manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
