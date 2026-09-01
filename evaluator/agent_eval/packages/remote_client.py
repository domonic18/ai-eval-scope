"""场景包远端客户端 — 从线上仓库拉取包归档。

提供抽象 :class:`RemotePackageClient`、内存假实现 :class:`FakeRemotePackageClient`
（离线单测用），以及真实 :class:`HttpRemotePackageClient`（ADR-01：从 Web
``GET /api/v1/scenarios/:id/packages/:assetId`` 公开读取，无需凭证）。
"""

from __future__ import annotations

import os
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import httpx

from agent_eval.packages.manifest import PackageManifest

# 仅由数字与点组成视为版本号（如 1.0.0），否则视为标签（production/latest/staging）。
_VERSION_RE = re.compile(r"^\d+(\.\d+)*$")


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


class HttpRemotePackageClient(RemotePackageClient):
    """真实 HTTP 远端客户端（ADR-01）。

    从 Web 平台 ``GET /api/v1/scenarios/:scenario/packages/:assetId`` 拉取包内容，
    **公开读、无需凭证**（与 catalog / rule-sets 端点一致）。响应 ``content`` 须为
    ``{manifest: {...}, files: {相对路径: 文本内容}}`` 结构，直接喂给
    :meth:`agent_eval.packages.PackageStore.install`。

    Args:
        base_url: Web 平台基址，如 ``http://localhost:9000``。
        timeout: 请求超时秒数。
    """

    def __init__(self, base_url: str, timeout: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def fetch(self, ref: str) -> RemotePackage:
        from agent_eval.packages.manager import parse_ref

        scenario, package_id, ver_or_label = parse_ref(ref)
        if not package_id:
            raise ValueError(
                f"pull ref 必须含 package id: {ref}（应为 scenario/package[:version_or_label]）"
            )
        url = f"{self.base_url}/api/v1/scenarios/{scenario}/packages/{package_id}"
        params: dict[str, str] = {}
        if ver_or_label:
            if _is_version(ver_or_label):
                params["version"] = ver_or_label
            else:
                params["label"] = ver_or_label
        try:
            resp = httpx.get(url, params=params, timeout=self.timeout)
        except httpx.HTTPError as e:  # 网络层错误
            raise RuntimeError(f"拉取失败（网络）: {e}") from e
        if resp.status_code == 404:
            raise FileNotFoundError(f"远端未找到包: {ref}")
        if resp.status_code >= 400:
            raise RuntimeError(f"拉取失败（HTTP {resp.status_code}）: {resp.text[:200]}")
        data = resp.json().get("package", {})
        content = data.get("content") or {}
        manifest_raw = content.get("manifest")
        files_raw = content.get("files") or {}
        if not isinstance(manifest_raw, dict):
            raise RuntimeError(f"远端包内容缺少 manifest: {ref}")
        manifest = PackageManifest.model_validate(manifest_raw)
        # JSON 文件值为字符串，统一编码为字节以契合 RemotePackage.files 契约。
        files = {
            rel: v.encode("utf-8") if isinstance(v, str) else v for rel, v in files_raw.items()
        }
        return RemotePackage(manifest=manifest, files=files)


def _is_version(s: str) -> bool:
    return bool(_VERSION_RE.match(s))


def get_remote_client() -> RemotePackageClient | None:
    """返回远端包客户端。

    若配置了环境变量 ``AGENT_EVAL_REGISTRY_URL``（Web 平台基址），返回真实
    :class:`HttpRemotePackageClient`；否则返回 ``None``（CLI ``scenario pull`` 据此
    提示未配置）。测试可 monkeypatch 本函数注入假客户端。
    """
    base_url = os.environ.get("AGENT_EVAL_REGISTRY_URL")
    if not base_url:
        return None
    return HttpRemotePackageClient(base_url)
