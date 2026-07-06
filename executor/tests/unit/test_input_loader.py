"""input_loader 单元测试 — zip 探测/解压/zip-slip 防护 + presigned HTTP GET。"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from eval_executor.storage import input_loader as il


def test_is_zip_detects_magic() -> None:
    assert il._is_zip(b"PK\x03\x04") is True
    assert il._is_zip(b"# hello") is False


def test_extract_zip_writes_files(tmp_path: Path) -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("a.md", "hello")
        zf.writestr("nested/b.html", "<html/>")
    il._extract_zip(buf.getvalue(), tmp_path)

    assert (tmp_path / "a.md").read_text() == "hello"
    assert (tmp_path / "nested" / "b.html").exists()


def test_extract_zip_rejects_slip(tmp_path: Path) -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("../evil.md", "x")
    with pytest.raises(ValueError, match="zip-slip"):
        il._extract_zip(buf.getvalue(), tmp_path)


def test_decode_zip_name_keeps_utf8() -> None:
    info = zipfile.ZipInfo(filename="课程.md")
    info.flag_bits |= 0x800  # 标记为 UTF-8
    assert il._decode_zip_name(info) == "课程.md"


async def test_load_input_single_file(tmp_path: Path) -> None:
    resp = MagicMock()
    resp.content = b"# markdown"
    resp.raise_for_status = MagicMock()

    mock_client = MagicMock()
    mock_client.get = AsyncMock(return_value=resp)
    client_cm = MagicMock()
    client_cm.__aenter__ = AsyncMock(return_value=mock_client)
    client_cm.__aexit__ = AsyncMock(return_value=None)

    with patch.object(il.httpx, "AsyncClient", return_value=client_cm):
        await il.load_input(
            "http://presigned", "projects/p/eval/jobs/j1/input.md", tmp_path, timeout=5.0
        )

    assert (tmp_path / "input.md").read_bytes() == b"# markdown"


async def test_load_input_zip(tmp_path: Path) -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("lesson.md", "# zipped")
    data = buf.getvalue()

    resp = MagicMock()
    resp.content = data
    resp.raise_for_status = MagicMock()

    mock_client = MagicMock()
    mock_client.get = AsyncMock(return_value=resp)
    client_cm = MagicMock()
    client_cm.__aenter__ = AsyncMock(return_value=mock_client)
    client_cm.__aexit__ = AsyncMock(return_value=None)

    with patch.object(il.httpx, "AsyncClient", return_value=client_cm):
        await il.load_input(
            "http://presigned", "projects/p/eval/jobs/j1/input.zip", tmp_path, timeout=5.0
        )

    assert (tmp_path / "lesson.md").read_text() == "# zipped"
