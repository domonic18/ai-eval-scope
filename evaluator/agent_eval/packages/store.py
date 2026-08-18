"""PackageStore — 本地与内置场景包仓库的读写。

两类仓库：
- **内置包**：随 pip 发布，位于 ``assets/packages/``（``paths.packages_dir``）。
- **本地缓存**：用户包与 ``pull`` 产物，位于 ``AGENT_EVAL_PACKAGE_DIR`` 或
  ``~/.agent_eval/packages/``，按 ``<scenario>/<package>/<version>/`` 组织。

清单（``agent_eval.yaml``）是唯一真相来源；目录约定为
``<scenario>/<package>/<version>/agent_eval.yaml``，但 list 时以递归发现清单为准，
兼容内置包的 ``<scenario>/<version>/`` 简化形态。
"""

from __future__ import annotations

import os
from pathlib import Path

from agent_eval.config.paths import paths
from agent_eval.core.exceptions import ScenarioPackageError
from agent_eval.packages.manifest import (
    MANIFEST_FILENAME,
    PackageManifest,
    ResolvedPackage,
    load_manifest,
)


def default_local_root() -> Path:
    """本地包缓存根目录（可由 ``AGENT_EVAL_PACKAGE_DIR`` 覆盖）。"""
    env = os.environ.get("AGENT_EVAL_PACKAGE_DIR")
    return Path(env).expanduser().resolve() if env else Path.home() / ".agent_eval" / "packages"


class PackageStore:
    """场景包仓库读写。

    Args:
        builtin_root: 内置包根（默认 ``paths.packages_dir``）。
        local_root: 本地缓存根（默认 :func:`default_local_root`）。
    """

    def __init__(self, builtin_root: Path | None = None, local_root: Path | None = None) -> None:
        self.builtin_root = Path(builtin_root) if builtin_root else paths.packages_dir
        self.local_root = Path(local_root) if local_root else default_local_root()

    # ── 读 ────────────────────────────────────────────────────────────────

    def list_all(self) -> list[ResolvedPackage]:
        """列出内置 + 本地缓存中的全部场景包。"""
        return self._list(self.builtin_root, "builtin") + self._list(self.local_root, "local")

    def list_builtin(self) -> list[ResolvedPackage]:
        return self._list(self.builtin_root, "builtin")

    def list_local(self) -> list[ResolvedPackage]:
        return self._list(self.local_root, "local")

    def find(
        self,
        scenario: str,
        package_id: str | None = None,
        version: str | None = None,
    ) -> list[ResolvedPackage]:
        """按 scenario[/package][/version] 过滤已解析包。"""
        out: list[ResolvedPackage] = []
        for pkg in self.list_all():
            if pkg.manifest.scenario != scenario:
                continue
            if package_id is not None and pkg.manifest.id != package_id:
                continue
            if version is not None and pkg.manifest.version != version:
                continue
            out.append(pkg)
        return out

    # ── 写（供 pull / init 使用）────────────────────────────────────────────

    def install(self, manifest: PackageManifest, files: dict[str, str | bytes]) -> Path:
        """将一个包写入本地缓存。

        Args:
            manifest: 包清单。
            files: ``{相对路径: 文本/字节内容}``，不含 ``agent_eval.yaml``（由 manifest 生成）。
        Returns:
            写入的包根目录。
        """
        root = self.local_root / manifest.scenario / manifest.id / manifest.version
        root.mkdir(parents=True, exist_ok=True)
        for rel, content in files.items():
            dest = root / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            mode = "wb" if isinstance(content, bytes) else "w"
            dest.write_text(content, encoding="utf-8") if mode == "w" else dest.write_bytes(content)
        # 清单最后写，确保目录已就绪
        (root / MANIFEST_FILENAME).write_text(_dump_manifest(manifest), encoding="utf-8")
        return root

    # ── 内部 ────────────────────────────────────────────────────────────────

    def _list(self, root: Path, source: str) -> list[ResolvedPackage]:
        if not root.exists():
            return []
        out: list[ResolvedPackage] = []
        for manifest_path in sorted(root.rglob(MANIFEST_FILENAME)):
            try:
                manifest = load_manifest(manifest_path.parent)
            except ScenarioPackageError:
                continue  # 跳过非法清单，list 不应整体失败
            out.append(ResolvedPackage(manifest=manifest, root=manifest_path.parent, source=source))
        return out


def _dump_manifest(manifest: PackageManifest) -> str:
    """序列化清单为 ``package:`` 段 YAML。"""
    import yaml

    return yaml.safe_dump(
        {"package": manifest.model_dump(exclude_none=True)},
        allow_unicode=True,
        sort_keys=False,
    )
