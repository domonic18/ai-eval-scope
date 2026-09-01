"""PackageStore — 内置 / 本地缓存 / 项目目录三源场景包仓库的读写。

三类仓库：
- **内置包**：随 pip 发布，位于 ``assets/packages/``（``paths.packages_dir``）。
- **本地缓存**：用户包与 ``pull`` 产物，位于 ``AGENT_EVAL_PACKAGE_DIR`` 或
  ``~/.agent_eval/packages/``，按 ``<scenario>/<package>/<version>/`` 组织。
- **项目包**：当前工作目录下的 ``*/agent_eval.yaml``（仅一级子目录）——
  ``scenario new`` / PackageAgent 的默认落盘位置（``./<id>-package/``），
  生成后无需注册即可被发现与执行（可由 ``AGENT_EVAL_PROJECT_DIR`` 覆盖）。

清单（``agent_eval.yaml``）是唯一真相来源；缓存/内置目录约定为
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


def default_project_root() -> Path:
    """项目包发现根目录（可由 ``AGENT_EVAL_PROJECT_DIR`` 覆盖；默认当前工作目录）。"""
    env = os.environ.get("AGENT_EVAL_PROJECT_DIR")
    return Path(env).expanduser().resolve() if env else Path.cwd()


def scenario_packages_root() -> Path:
    """workspace 内场景包**历史**落盘根（兼容旧包发现，不再是新包默认位置）。

    2026-09 起场景包按源资产对待，``scenario new`` 默认 cwd 直出 ``./<id>-package/``；
    本目录仅为 ``list_project`` 的兼容扫描根——旧位置已生成的包不搬家仍可见。
    注意与 ``workspace/packages/``（``pack`` 的 ExecutionPackage 产出物，manifest.json）
    是两个概念，勿混用。
    """
    from agent_eval.config.paths import paths

    return paths.default_workspace / "scenario-packages"


class PackageStore:
    """场景包仓库读写。

    Args:
        builtin_root: 内置包根（默认 ``paths.packages_dir``）。
        local_root: 本地缓存根（默认 :func:`default_local_root`）。
        project_root: 项目包发现根（默认 :func:`default_project_root`）。
    """

    def __init__(
        self,
        builtin_root: Path | None = None,
        local_root: Path | None = None,
        project_root: Path | None = None,
    ) -> None:
        self.builtin_root = Path(builtin_root) if builtin_root else paths.packages_dir
        self.local_root = Path(local_root) if local_root else default_local_root()
        self.project_root = Path(project_root) if project_root else default_project_root()

    # ── 读 ────────────────────────────────────────────────────────────────

    def list_all(self) -> list[ResolvedPackage]:
        """列出内置 + 本地缓存 + 项目目录中的全部场景包。"""
        return (
            self._list(self.builtin_root, "builtin")
            + self._list(self.local_root, "local")
            + self.list_project()
        )

    def list_builtin(self) -> list[ResolvedPackage]:
        return self._list(self.builtin_root, "builtin")

    def list_local(self) -> list[ResolvedPackage]:
        return self._list(self.local_root, "local")

    def list_project(self) -> list[ResolvedPackage]:
        """列出项目根与 workspace/scenario-packages 下**一级子目录**含清单的场景包。

        每个根只扫一层（非 rglob）：项目根常是代码仓库（如 ``evaluator/``），递归会把
        内置包经 ``agent_eval/assets/packages/`` 重复发现、还会捞到依赖目录。
        """
        out: list[ResolvedPackage] = []
        seen: set[Path] = set()
        for root in (self.project_root, scenario_packages_root()):
            if not root.is_dir():
                continue
            for child in sorted(root.iterdir()):
                if not child.is_dir() or child.name.startswith(".") or child.name == "__pycache__":
                    continue
                if not (child / MANIFEST_FILENAME).is_file():
                    continue
                key = child.resolve()
                if key in seen:  # 双根重叠时去重
                    continue
                try:
                    manifest = load_manifest(child)
                except ScenarioPackageError:
                    continue  # 跳过非法清单，list 不应整体失败
                seen.add(key)
                out.append(ResolvedPackage(manifest=manifest, root=child, source="project"))
        return out

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
            if isinstance(content, bytes):
                dest.write_bytes(content)
            else:
                dest.write_text(content, encoding="utf-8")
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
