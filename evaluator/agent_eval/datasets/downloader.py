"""数据集下载器 — HuggingFace / ModelScope 双源实现。

第三方库（huggingface_hub / modelscope）惰性导入，缺失时抛 DatasetDownloadError
并给出安装指引（参照 agent_eval/observability/render.py 的 Playwright 懒加载范式）。
镜像端点与认证 token 通过环境变量透传给底层库，不在本模块硬编码：

* ``HF_ENDPOINT`` — HF 镜像（国内常用 https://hf-mirror.com）
* ``HF_TOKEN`` / ``HUGGING_FACE_HUB_TOKEN`` — HF 认证
* ``MODELSCOPE_API_TOKEN`` — ModelScope 认证
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from pathlib import Path

from agent_eval.core.exceptions import DatasetDownloadError
from agent_eval.core.types import DatasetSource

_INSTALL_HINT = "请执行: uv sync --extra datasets"


class DatasetDownloader(ABC):
    """下载器抽象基类。"""

    @abstractmethod
    def download(
        self,
        repo_id: str,
        target: Path,
        revision: str | None = None,
        token: str | None = None,
    ) -> Path:
        """下载数据集到 target 目录，返回目标路径。

        Args:
            repo_id: 数据集仓库标识（如 ``opencompass/ceval-exam``）。
            target: 落盘目标目录。
            revision: 版本标识（HF commit/branch/tag，MS 版本号）；None 取最新。
            token: 访问 token；None 时由底层库读取对应环境变量。
        """
        ...


class HuggingFaceDownloader(DatasetDownloader):
    """HuggingFace 下载器，基于 ``huggingface_hub.snapshot_download``。

    通过 ``local_dir`` 落盘到指定目录（而非默认 ~/.cache/huggingface），
    ``repo_type='dataset'`` 显式声明为数据集仓库。
    """

    def download(self, repo_id, target, revision=None, token=None):
        try:
            from huggingface_hub import snapshot_download
        except ImportError as e:  # pragma: no cover - 依赖缺失分支
            raise DatasetDownloadError(
                f"huggingface_hub 未安装。{_INSTALL_HINT}"
            ) from e

        target.mkdir(parents=True, exist_ok=True)
        snapshot_download(
            repo_id=repo_id,
            repo_type="dataset",
            local_dir=str(target),
            revision=revision,
            token=token,
        )
        return target


class ModelScopeDownloader(DatasetDownloader):
    """ModelScope 下载器，基于 ``dataset_snapshot_download`` 整仓下载原始文件。

    优先使用 ``local_dir`` 精确落盘；旧版 modelscope 不支持时回退到 cache_dir。
    """

    def download(self, repo_id, target, revision=None, token=None):
        try:
            from modelscope.hub.snapshot_download import dataset_snapshot_download
        except ImportError as e:  # pragma: no cover - 依赖缺失分支
            raise DatasetDownloadError(f"modelscope 未安装。{_INSTALL_HINT}") from e

        if token:
            os.environ.setdefault("MODELSCOPE_API_TOKEN", token)
        target.mkdir(parents=True, exist_ok=True)
        # revision=None 时用 modelscope 默认（master）；显式传 None 会导致下载失败
        kwargs: dict[str, object] = {
            "dataset_id": repo_id,
            "local_dir": str(target),
            "token": token,
        }
        if revision is not None:
            kwargs["revision"] = revision
        dataset_snapshot_download(**kwargs)
        return target


def get_downloader(source: DatasetSource | str) -> DatasetDownloader:
    """工厂：按 source 返回下载器实例。

    Args:
        source: DatasetSource 枚举或其字符串值（"huggingface" / "modelscope"）。

    Raises:
        DatasetDownloadError: 不支持的源。
    """
    if not isinstance(source, DatasetSource):
        try:
            source = DatasetSource(source)
        except ValueError as e:
            raise DatasetDownloadError(f"不支持的下载源: {source}") from e
    if source is DatasetSource.HUGGINGFACE:
        return HuggingFaceDownloader()
    if source is DatasetSource.MODELSCOPE:
        return ModelScopeDownloader()
    raise DatasetDownloadError(f"不支持的下载源: {source}")
