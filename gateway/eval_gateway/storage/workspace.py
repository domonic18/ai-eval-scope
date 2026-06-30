"""上传内容物化 — 把 multipart 或内联内容落到临时目录，供 PackageBuilder 打包。"""

from __future__ import annotations

import zipfile
from pathlib import Path
from typing import Any

from starlette.datastructures import UploadFile

from eval_gateway.core.logging import get_logger
from eval_gateway.core.types import Scope

LOG = get_logger(__name__)


async def materialize_upload(
    upload: UploadFile,
    temp_dir: Path,
    *,
    max_size: int = 50 * 1024 * 1024,
) -> tuple[str, Scope]:
    """物化上传文件：zip 解压到 temp_dir/contents；单文件直接写入 temp_dir/contents。

    Returns:
        (input_ref, scope) — input_ref 为物化目录路径，scope 为单元或单页。
    """
    contents_dir = temp_dir / "contents"
    contents_dir.mkdir(parents=True, exist_ok=True)

    filename = upload.filename or "input"
    suffix = Path(filename).suffix.lower()
    data = await upload.read()
    if len(data) > max_size:
        raise ValueError(f"upload exceeds max size {max_size} bytes")

    if suffix == ".zip" or (data[:2] == b"PK"):
        _extract_zip(data, contents_dir)
        scope = Scope.UNIT
    else:
        target = contents_dir / filename
        target.write_bytes(data)
        scope = Scope.SINGLE

    await upload.close()
    LOG.info("materialized.upload", path=str(contents_dir), scope=scope.value, size=len(data))
    return str(contents_dir), scope


def materialize_inline(
    content: dict[str, Any],
    temp_dir: Path,
) -> tuple[str, Scope]:
    """物化内联 JSON 内容到 temp_dir/contents/{filename}。"""
    contents_dir = temp_dir / "contents"
    contents_dir.mkdir(parents=True, exist_ok=True)

    filename = content.get("filename", "input.md")
    text = content.get("text", "")
    target = contents_dir / filename
    target.write_text(text, encoding="utf-8")
    return str(contents_dir), Scope.SINGLE


def _extract_zip(data: bytes, contents_dir: Path) -> None:
    """安全解压 zip，限制总大小与路径穿越。"""
    max_uncompressed = 100 * 1024 * 1024
    total = 0
    with zipfile.ZipFile(file=__import__("io").BytesIO(data)) as zf:
        for info in zf.infolist():
            total += info.file_size
            if total > max_uncompressed:
                raise ValueError("zip uncompressed size exceeds 100MB")
            target = contents_dir / info.filename
            if not _is_safe_path(contents_dir, target):
                raise ValueError(f"zip-slip detected: {info.filename}")
        zf.extractall(contents_dir)


def _is_safe_path(base: Path, target: Path) -> bool:
    """防止 zip-slip。"""
    try:
        target.resolve().relative_to(base.resolve())
    except ValueError:
        return False
    return True
