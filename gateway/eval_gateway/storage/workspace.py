"""上传内容物化 — 把 multipart 或内联内容落到临时目录，供 PackageBuilder 打包。"""

from __future__ import annotations

import io
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
    """安全解压 zip，限制总大小与路径穿越；修正非 UTF-8 文件名编码（避免中文乱码）。"""
    max_uncompressed = 100 * 1024 * 1024
    total = 0
    with zipfile.ZipFile(file=io.BytesIO(data)) as zf:
        infos = zf.infolist()
        # 先校验全部（大小 + 路径穿越 + 编码修正），再统一解压，避免中途失败留下部分文件
        for info in infos:
            total += info.file_size
            if total > max_uncompressed:
                raise ValueError("zip uncompressed size exceeds 100MB")
            info.filename = _decode_zip_name(info)
            if not _is_safe_path(contents_dir, contents_dir / info.filename):
                raise ValueError(f"zip-slip detected: {info.filename}")
        for info in infos:
            zf.extract(info, contents_dir)


def _decode_zip_name(info: zipfile.ZipInfo) -> str:
    """修正 zip 条目文件名编码。

    ZIP 规范默认文件名编码为 CP437；仅当通用位标志 bit 11（0x800）置位时才为 UTF-8。
    Python ``zipfile`` 遵此规范——未置位时按 CP437 解码，于是以 UTF-8/GBK 实际存储的
    中文文件名会被误解为乱码（如 ``大单元`` → ``σñºσìòσàâ``），并经 evaluator 摄取入库。
    此处把文件名回滚为原始字节后，依次按 UTF-8 / GBK / GB18030 重新解码：已是 ASCII
    或带 UTF-8 标记的文件名原样返回，无法还原时保留原值（幂等、不丢数据）。
    """
    name = info.filename
    if info.flag_bits & 0x800:  # UTF-8 标记已置位 → filename 已是正确的 UTF-8
        return name
    try:
        raw = name.encode("cp437")
    except (UnicodeEncodeError, LookupError):
        return name  # 含 cp437 不可编码字符（如已正确解码的 CJK）→ 无需也无法回滚
    for enc in ("utf-8", "gbk", "gb18030"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return name


def _is_safe_path(base: Path, target: Path) -> bool:
    """防止 zip-slip。"""
    try:
        target.resolve().relative_to(base.resolve())
    except ValueError:
        return False
    return True
