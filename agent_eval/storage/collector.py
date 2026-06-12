"""DirectoryCollector — 目录遍历与清单生成。

遍历指定目录结构，收集匹配文件（如 HTML），生成 _manifest.json 清单，
记录模块、文件类型、层级深度等信息。
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from pathlib import Path

from agent_eval.storage.package import (
    DirectoryManifest,
    DirectoryManifestFile,
    DirectoryManifestModule,
)


@dataclass
class CollectedFile:
    """采集到的单个文件信息。"""

    relative_path: str  # 相对于根目录的路径
    absolute_path: Path
    file_size: int
    depth: int  # 目录深度（根目录为 0）
    parent_module: str  # 直接父目录名
    file_type: str  # 扩展名（如 ".html"）


class DirectoryCollector:
    """遍历目录结构，收集指定类型的文件，保留层级信息。

    使用示例:
        collector = DirectoryCollector(
            root_dir=Path("/path/to/大单元学习总导/"),
            file_patterns=["*.html", "*.htm"],
        )
        manifest = collector.collect()
        collector.write_manifest(manifest, output_dir)
    """

    def __init__(
        self,
        root_dir: Path | str,
        file_patterns: list[str] | None = None,
        exclude_dirs: list[str] | None = None,
        max_depth: int = 10,
    ) -> None:
        """初始化 DirectoryCollector。

        Args:
            root_dir: 要遍历的根目录。
            file_patterns: 文件匹配模式（如 ["*.html", "*.htm"]）。
            exclude_dirs: 排除的目录名列表。
            max_depth: 最大遍历深度。
        """
        self.root_dir = Path(root_dir)
        self.file_patterns = file_patterns or ["*.html", "*.htm"]
        self.exclude_dirs = set(exclude_dirs or ["__MACOSX", ".git", ".DS_Store"])
        self.max_depth = max_depth

    def collect(self) -> DirectoryManifest:
        """遍历目录树，收集所有匹配文件，返回目录清单。

        Returns:
            DirectoryManifest 实例。
        """
        if not self.root_dir.exists():
            raise FileNotFoundError(f"目录不存在: {self.root_dir}")
        if not self.root_dir.is_dir():
            raise NotADirectoryError(f"不是目录: {self.root_dir}")

        files = self._collect_files()
        modules = self._build_modules(files)
        file_types = self._count_file_types(files)
        max_depth = max((f.depth for f in files), default=0)

        return DirectoryManifest(
            mode="directory",
            root_dir=str(self.root_dir),
            total_files=len(files),
            file_types=file_types,
            hierarchy_depth=max_depth,
            modules=modules,
        )

    def collect_flat(self) -> list[CollectedFile]:
        """返回扁平化的文件列表（不含层级/模块信息）。"""
        return self._collect_files()

    def write_manifest(self, manifest: DirectoryManifest, output_dir: Path | str) -> Path:
        """将目录清单写入 _manifest.json。

        Args:
            manifest: 目录清单。
            output_dir: 输出目录。

        Returns:
            _manifest.json 文件路径。
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = output_dir / "_manifest.json"
        manifest_path.write_text(
            manifest.model_dump_json(indent=2), encoding="utf-8",
        )
        return manifest_path

    def _collect_files(self) -> list[CollectedFile]:
        """遍历目录树，收集所有匹配文件。"""
        files: list[CollectedFile] = []

        for path in self.root_dir.rglob("*"):
            if not path.is_file():
                continue
            if not self._matches_pattern(path):
                continue
            if self._is_excluded(path):
                continue

            rel_path = path.relative_to(self.root_dir)
            depth = len(rel_path.parts) - 1  # 文件所在深度
            parent_module = rel_path.parts[0] if rel_path.parts else ""

            files.append(CollectedFile(
                relative_path=str(rel_path),
                absolute_path=path,
                file_size=path.stat().st_size,
                depth=depth,
                parent_module=parent_module,
                file_type=path.suffix.lower(),
            ))

        return sorted(files, key=lambda f: f.relative_path)

    def _build_modules(self, files: list[CollectedFile]) -> list[DirectoryManifestModule]:
        """按顶层目录将文件组织为模块。"""
        modules_dict: dict[str, list[CollectedFile]] = {}
        for f in files:
            modules_dict.setdefault(f.parent_module, []).append(f)

        modules: list[DirectoryManifestModule] = []
        for module_name, module_files in modules_dict.items():
            children = [
                DirectoryManifestFile(
                    name=f.absolute_path.stem,
                    path=f.relative_path,
                    depth=f.depth,
                    size=f.file_size,
                )
                for f in module_files
            ]
            modules.append(DirectoryManifestModule(
                name=module_name,
                path=f"{module_name}/",
                file_count=len(module_files),
                children=children,
            ))

        return modules

    def _count_file_types(self, files: list[CollectedFile]) -> dict[str, int]:
        """按扩展名统计文件数量。"""
        counts: dict[str, int] = {}
        for f in files:
            counts[f.file_type] = counts.get(f.file_type, 0) + 1
        return counts

    def _matches_pattern(self, path: Path) -> bool:
        """检查文件名是否匹配任一模式。"""
        name = path.name
        return any(fnmatch.fnmatch(name, pattern) for pattern in self.file_patterns)

    def _is_excluded(self, path: Path) -> bool:
        """检查文件路径是否包含排除的目录或文件名。"""
        rel_parts = path.relative_to(self.root_dir).parts
        # 排除包含在 exclude_dirs 中的目录段
        if any(part in self.exclude_dirs for part in rel_parts):
            return True
        # 排除隐藏/系统文件（以 . 开头）
        if path.name.startswith("."):
            return True
        return False
