"""DirectoryCollector 测试。"""

import json
from pathlib import Path

import pytest

from agent_eval.storage.collector import DirectoryCollector

FIXTURES = Path(__file__).parent.parent / "fixtures"
GOLDEN_DIR = FIXTURES / "golden" / "directory_sample"


class TestDirectoryCollector:
    def test_collect_html_files(self) -> None:
        collector = DirectoryCollector(
            root_dir=GOLDEN_DIR,
            file_patterns=["*.html"],
        )
        manifest = collector.collect()

        assert manifest.mode == "directory"
        assert manifest.total_files == 4
        assert manifest.file_types == {".html": 4}
        assert len(manifest.modules) == 2  # M1 and M2

    def test_modules_structure(self) -> None:
        collector = DirectoryCollector(
            root_dir=GOLDEN_DIR,
            file_patterns=["*.html"],
        )
        manifest = collector.collect()

        module_names = [m.name for m in manifest.modules]
        assert "M1 大单元概述" in module_names
        assert "M2 学习新知" in module_names

        # M1 有 2 个文件，M2 有 2 个文件
        m1 = next(m for m in manifest.modules if "M1" in m.name)
        assert m1.file_count == 2
        m2 = next(m for m in manifest.modules if "M2" in m.name)
        assert m2.file_count == 2

    def test_hierarchy_depth(self) -> None:
        collector = DirectoryCollector(
            root_dir=GOLDEN_DIR,
            file_patterns=["*.html"],
        )
        manifest = collector.collect()
        # 目录结构为 M*/.../.../*.html，最大深度为 3
        assert manifest.hierarchy_depth == 3

    def test_collect_flat(self) -> None:
        collector = DirectoryCollector(
            root_dir=GOLDEN_DIR,
            file_patterns=["*.html"],
        )
        files = collector.collect_flat()
        assert len(files) == 4
        assert all(f.file_type == ".html" for f in files)

    def test_file_size(self) -> None:
        collector = DirectoryCollector(
            root_dir=GOLDEN_DIR,
            file_patterns=["*.html"],
        )
        files = collector.collect_flat()
        assert all(f.file_size > 0 for f in files)

    def test_write_manifest(self, tmp_path: Path) -> None:
        collector = DirectoryCollector(
            root_dir=GOLDEN_DIR,
            file_patterns=["*.html"],
        )
        manifest = collector.collect()
        manifest_path = collector.write_manifest(manifest, tmp_path / "output")

        assert manifest_path.exists()
        assert manifest_path.name == "_manifest.json"

        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert data["mode"] == "directory"
        assert data["total_files"] == 4
        assert len(data["modules"]) == 2

    def test_nonexistent_directory(self) -> None:
        collector = DirectoryCollector(root_dir="/tmp/nonexistent_dir_xyz")
        with pytest.raises(FileNotFoundError):
            collector.collect()

    def test_file_pattern_filter(self, tmp_path: Path) -> None:
        """测试文件匹配模式过滤。"""
        # 创建测试文件
        (tmp_path / "test.html").write_text("<html></html>")
        (tmp_path / "test.md").write_text("# Test")
        (tmp_path / "test.txt").write_text("plain text")

        # 只匹配 html
        collector = DirectoryCollector(
            root_dir=tmp_path,
            file_patterns=["*.html"],
        )
        manifest = collector.collect()
        assert manifest.total_files == 1
        assert manifest.file_types == {".html": 1}

    def test_exclude_dirs(self, tmp_path: Path) -> None:
        """测试排除目录。"""
        (tmp_path / "__MACOSX" / "sub").mkdir(parents=True)
        (tmp_path / "__MACOSX" / "sub" / "file.html").write_text("<html></html>")
        (tmp_path / "normal").mkdir()
        (tmp_path / "normal" / "good.html").write_text("<html></html>")

        collector = DirectoryCollector(
            root_dir=tmp_path,
            file_patterns=["*.html"],
            exclude_dirs=["__MACOSX"],
        )
        manifest = collector.collect()
        assert manifest.total_files == 1  # 只收集 normal/good.html
