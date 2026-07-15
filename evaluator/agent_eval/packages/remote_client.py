"""场景包远端客户端 — 从线上仓库拉取包归档。

Phase 2 仅定义抽象接口与可注入的假实现，便于 ``agent-eval package pull`` 的离线单测。
真实 HTTP 拉取（走 eval-gateway 的 pull-token 流程）在 Phase 3 服务端就绪后补全。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from agent_eval.packages.manifest import PackageManifest


@dataclass
class RemotePackage:
    """远端拉取到的包归档（内存形态）。"""

    manifest: PackageManifest
    files: dict[str, bytes] = field(default_factory=dict)  # 相对路径 → 字节内容


class RemotePackageClient(ABC):
    """远端包仓库客户端抽象。"""

    @abstractmethod
    def fetch(self, ref: str) -> RemotePackage:
        """按 ``scenario/package:version_or_label`` 拉取包归档。"""
        raise NotImplementedError


class FakeRemotePackageClient(RemotePackageClient):
    """内存假客户端，供测试与 demo 注入。

    Args:
        packages: ``{ref: RemotePackage}`` 预置条目。
    """

    def __init__(self, packages: dict[str, RemotePackage] | None = None) -> None:
        self.packages = dict(packages or {})

    def add(self, ref: str, pkg: RemotePackage) -> None:
        self.packages[ref] = pkg

    def fetch(self, ref: str) -> RemotePackage:
        if ref not in self.packages:
            raise KeyError(f"FakeRemotePackageClient 未预置包: {ref}")
        return self.packages[ref]


def get_remote_client() -> RemotePackageClient | None:
    """返回远端包客户端。

    Phase 2 未接真实 HTTP（服务端在 Phase 3 就绪），返回 ``None``；
    CLI ``package pull`` 据此给出明确提示。测试通过 monkeypatch 本函数注入假客户端。
    """
    return None
