"""storage/package.py 工具函数测试。"""

from __future__ import annotations

import shutil
from pathlib import Path

from agent_eval.storage.collector import DirectoryCollector
from agent_eval.storage.package import find_orphan_files


def _build_output_with_manifest(tmp_path: Path) -> tuple[Path, object]:
    """构造 output 目录（含 2 个 html）+ 对应 DirectoryManifest，返回 (output, manifest)。"""
    src = tmp_path / "src"
    (src / "mod").mkdir(parents=True)
    (src / "mod" / "a.html").write_text("a", encoding="utf-8")
    (src / "mod" / "b.html").write_text("b", encoding="utf-8")
    manifest = DirectoryCollector(root_dir=src, file_patterns=["*.html"]).collect()
    output = tmp_path / "output"
    shutil.copytree(src, output)  # 结构与 src 一致 → output/mod/{a,b}.html
    return output, manifest


class TestFindOrphanFiles:
    def test_detects_orphan(self, tmp_path: Path) -> None:
        output, manifest = _build_output_with_manifest(tmp_path)
        (output / "mod" / "orphan.html").write_text("x", encoding="utf-8")

        orphans = find_orphan_files(output, manifest)
        assert [p.name for p in orphans] == ["orphan.html"]

    def test_empty_when_clean(self, tmp_path: Path) -> None:
        output, manifest = _build_output_with_manifest(tmp_path)
        assert find_orphan_files(output, manifest) == []

    def test_ignores_manifest_json_itself(self, tmp_path: Path) -> None:
        output, manifest = _build_output_with_manifest(tmp_path)
        # _manifest.json 是清单文件本身，不应算孤儿
        (output / "_manifest.json").write_text("{}", encoding="utf-8")
        assert find_orphan_files(output, manifest) == []
