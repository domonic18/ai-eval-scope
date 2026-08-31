"""输入下载 -- 经 Web 签发的 presigned URL HTTP GET 下载输入并物化到本地。

executor **不持有对象存储凭据**：输入由 Web 上传到对象存储后签发短期 presigned GET URL，
经 SCF 事件（或 eval_jobs.input_presigned_url）传给 executor，executor 仅做 HTTP GET。

- zip → 安全解压到 dest_dir（zip-slip 防护 + 中文文件名编码修正）；
- 单文件 → 按 object_key 基名写入 dest_dir。
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import httpx

from eval_executor.core.logging import get_logger

LOG = get_logger(__name__)

_MAX_UNCOMPRESSED = 100 * 1024 * 1024


def _is_zip(data: bytes) -> bool:
    return data[:2] == b"PK"


async def load_input(
    url: str,
    object_key: str,
    dest_dir: Path,
    *,
    timeout: float = 120.0,
) -> Path:
    """下载并物化输入到 dest_dir，返回 dest_dir。

    - url：Web 签发的 presigned GET URL（短期）。
    - object_key：对象存储 key（仅用于取单文件基名，不用于访问对象存储）。
    """
    dest_dir.mkdir(parents=True, exist_ok=True)

    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.get(url)
        resp.raise_for_status()
    data = resp.content

    if _is_zip(data):
        _extract_zip(data, dest_dir)
        LOG.info("input.loaded_zip", object_key=object_key, size=len(data))
    else:
        filename = Path(object_key).name or "input"
        (dest_dir / filename).write_bytes(data)
        LOG.info("input.loaded_file", object_key=object_key, size=len(data))
    return dest_dir


def _extract_zip(data: bytes, dest_dir: Path) -> None:
    """安全解压 zip，限制总大小与路径穿越；修正非 UTF-8 文件名编码（避免中文乱码）。"""
    total = 0
    with zipfile.ZipFile(file=io.BytesIO(data)) as zf:
        infos = zf.infolist()
        # 先校验全部（大小 + 路径穿越 + 编码修正），再统一解压，避免中途失败留下部分文件
        for info in infos:
            total += info.file_size
            if total > _MAX_UNCOMPRESSED:
                raise ValueError("zip uncompressed size exceeds 100MB")
            info.filename = _decode_zip_name(info)
            if not _is_safe_path(dest_dir, dest_dir / info.filename):
                raise ValueError(f"zip-slip detected: {info.filename}")
        for info in infos:
            zf.extract(info, dest_dir)


def _decode_zip_name(info: zipfile.ZipInfo) -> str:
    """修正 zip 条目文件名编码（CP437 → UTF-8/GBK/GB18030）。"""
    name = info.filename
    if info.flag_bits & 0x800:  # UTF-8 标记已置位
        return name
    try:
        raw = name.encode("cp437")
    except (UnicodeEncodeError, LookupError):
        return name
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
