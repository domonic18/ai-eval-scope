"""builder 单元测试 — 验证打包复用 PackageBuilder。"""

from __future__ import annotations

from pathlib import Path

from eval_executor.executor.builder import _content_hash, build_package


def test_content_hash_stable(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "a.md").write_text("hello")
    (source / "b.html").write_text("<html></html>")

    h1 = _content_hash(source)
    h2 = _content_hash(source)
    assert h1 is not None
    assert h1 == h2


def test_content_hash_ignores_hidden_files(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "a.md").write_text("hello")
    (source / ".DS_Store").write_text("ignore me")

    h = _content_hash(source)
    # 仅 a.md 参与哈希
    only_a = tmp_path / "only_a"
    only_a.mkdir()
    (only_a / "a.md").write_text("hello")
    assert h == _content_hash(only_a)


def test_build_package_creates_manifest_and_output(tmp_path: Path) -> None:
    source = tmp_path / "unit-fractions"
    source.mkdir()
    (source / "lesson-01.md").write_text("# 分数入门")

    package_dir = tmp_path / "package"
    result = build_package(
        input_dir=source,
        package_dir=package_dir,
        task_title="分数入门",
        task_subject="math",
        task_id="fractions-01",
    )

    assert result == package_dir
    assert (package_dir / "manifest.json").exists()
    assert (package_dir / "task.json").exists()
    assert (package_dir / "output" / "lesson-01.md").exists()

    task_text = (package_dir / "task.json").read_text(encoding="utf-8")
    assert "分数入门" in task_text
    assert "math" in task_text
