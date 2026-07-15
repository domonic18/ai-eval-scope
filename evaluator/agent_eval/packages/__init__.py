"""场景包（Scenario Package）管理 — 对齐 13 配置管理设计 §四/§五。

一个场景包是规则/提示词/数据集等配置资产的可分发、可版本化单元，由
``agent_eval.yaml`` 清单描述。本子包提供：
- :class:`PackageManifest` / :class:`ResolvedPackage`：清单与解析结果
- :class:`PackageStore`：内置包 + 本地缓存仓库读写
- :class:`PackageManager`：按 scenario/package:version_or_label 解析
- :class:`RemotePackageClient`：线上拉取抽象（Phase 2 仅假实现）
"""

from __future__ import annotations

from agent_eval.packages.manager import PackageManager, parse_ref
from agent_eval.packages.manifest import (
    MANIFEST_FILENAME,
    PackageManifest,
    ResolvedPackage,
    load_manifest,
)
from agent_eval.packages.remote_client import (
    FakeRemotePackageClient,
    RemotePackage,
    RemotePackageClient,
    get_remote_client,
)
from agent_eval.packages.store import PackageStore
from agent_eval.packages.store import default_local_root as local_root

__all__ = [
    "MANIFEST_FILENAME",
    "FakeRemotePackageClient",
    "PackageManifest",
    "PackageManager",
    "PackageStore",
    "RemotePackage",
    "RemotePackageClient",
    "ResolvedPackage",
    "get_remote_client",
    "load_manifest",
    "local_root",
    "parse_ref",
]
