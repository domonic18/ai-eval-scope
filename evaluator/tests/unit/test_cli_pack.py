"""pack 命令的样本内容寻址哈希测试（docs/arch/13 §5）。

内容指纹保证：同内容同哈希（稳定可对比）、不同内容不同哈希（解决末级目录同名冲突）、
隐藏文件不参与（跨环境稳定）、空目录回退。
"""

from __future__ import annotations

from pathlib import Path

from agent_eval.cli.main import _content_hash


def test_content_hash_stable_same_content(tmp_path: Path) -> None:
    """同内容（不同目录）→ 同哈希：稳定性，支持纵向对比。"""
    d1, d2 = tmp_path / "a", tmp_path / "b"
    d1.mkdir()
    d2.mkdir()
    for d in (d1, d2):
        (d / "course.html").write_text("<html>课件</html>", encoding="utf-8")
        (d / "data.json").write_text('{"k":1}', encoding="utf-8")

    assert _content_hash(d1) == _content_hash(d2)
    assert _content_hash(d1) is not None


def test_content_hash_differs_for_different_content(tmp_path: Path) -> None:
    """不同内容 → 不同哈希：唯一性，解决"末级目录同名"冲突。"""
    d1, d2 = tmp_path / "a", tmp_path / "b"
    d1.mkdir()
    d2.mkdir()
    (d1 / "course.html").write_text("<html>课件 A</html>", encoding="utf-8")
    (d2 / "course.html").write_text("<html>课件 B</html>", encoding="utf-8")

    assert _content_hash(d1) != _content_hash(d2)


def test_content_hash_ignores_hidden_files(tmp_path: Path) -> None:
    """隐藏文件（.DS_Store 等）不参与哈希，保证跨机器/系统稳定。"""
    d = tmp_path / "pkg"
    d.mkdir()
    (d / "course.html").write_text("内容", encoding="utf-8")
    base = _content_hash(d)

    (d / ".DS_Store").write_bytes(b"macOS junk")
    assert _content_hash(d) == base


def test_content_hash_empty_dir_returns_none(tmp_path: Path) -> None:
    """空目录 → None：调用方回退到末级目录名。"""
    d = tmp_path / "empty"
    d.mkdir()
    assert _content_hash(d) is None
