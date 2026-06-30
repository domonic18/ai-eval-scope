"""workspace zip 解压单元测试 — 重点覆盖中文文件名编码修正（CP437 → UTF-8/GBK）。

背景：ZIP 规范默认文件名编码为 CP437，仅当通用位标志 bit 11（0x800）置位时为 UTF-8。
第三方打包器（Windows 资源管理器、部分 Java/Go 库）常把中文文件名按 UTF-8 字节写入
却不设该标记，Python ``zipfile`` 读取时便按 CP437 解码 → 乱码落盘 → 经 evaluator
摄取入库（表现为制品列表中文文件名乱码，ASCII 部分正常）。
"""

from __future__ import annotations

import io
import struct
import zipfile
from pathlib import Path

import pytest

from eval_gateway.storage.workspace import _decode_zip_name, _extract_zip


def _strip_utf8_flag(zip_bytes: bytes) -> bytes:
    """模拟第三方打包器：清除 zip 的 UTF-8 标记（local + central directory）。

    清除后文件名字段仍是 UTF-8 字节，但读取时按 CP437 解码 → 复现线上乱码 zip。
    """
    ba = bytearray(zip_bytes)
    # local file header: 标志位在签名后偏移 6；central directory: 偏移 8
    for sig, flag_off in ((b"PK\x03\x04", 6), (b"PK\x01\x02", 8)):
        i = 0
        while True:
            j = ba.find(sig, i)
            if j < 0:
                break
            flags = struct.unpack_from("<H", ba, j + flag_off)[0]
            struct.pack_into("<H", ba, j + flag_off, flags & ~0x800)
            i = j + 4
    return bytes(ba)


# ── _decode_zip_name 单元测试 ──────────────────────────────────────────────


def test_decode_zip_name_restores_cp437_mangled_utf8() -> None:
    """未标 UTF-8 的 UTF-8 文件名（线上真实场景）应还原为中文。"""
    info = zipfile.ZipInfo("x")
    info.flag_bits = 0
    info.filename = "大单元学习总导.html".encode().decode("cp437")
    assert _decode_zip_name(info) == "大单元学习总导.html"


def test_decode_zip_name_keeps_utf8_flagged() -> None:
    """带 UTF-8 标记的文件名已正确，原样返回。"""
    info = zipfile.ZipInfo("大单元.html")
    info.flag_bits = 0x800
    assert _decode_zip_name(info) == "大单元.html"


def test_decode_zip_name_keeps_ascii() -> None:
    """纯 ASCII 文件名（如 _manifest.json）不受影响。"""
    info = zipfile.ZipInfo("_manifest.json")
    info.flag_bits = 0
    assert _decode_zip_name(info) == "_manifest.json"


def test_decode_zip_name_gbk_fallback() -> None:
    """UTF-8 解码失败时回退 GBK（部分打包器用 GBK 存中文文件名）。"""
    info = zipfile.ZipInfo("x")
    info.flag_bits = 0
    info.filename = "课件.html".encode("gbk").decode("cp437")
    assert _decode_zip_name(info) == "课件.html"


def test_decode_zip_name_idempotent_on_correct_cjk() -> None:
    """已是正确中文（如重新解压）不应被误改：cp437 编码 CJK 失败 → 原样返回。"""
    info = zipfile.ZipInfo("大单元.html")
    info.flag_bits = 0
    assert _decode_zip_name(info) == "大单元.html"


# ── _extract_zip 端到端测试 ────────────────────────────────────────────────


def test_extract_zip_restores_non_utf8_chinese_filename(tmp_path: Path) -> None:
    """端到端：未标 UTF-8 的中文 zip 解压后文件名应正确还原。"""
    name = "output/大单元学习总导/构建性示例.html"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(zipfile.ZipInfo(name), b"<html></html>")
    data = _strip_utf8_flag(buf.getvalue())

    # 修复前：直接读取会得到 CP437 乱码（确认测试用例真实）
    with zipfile.ZipFile(io.BytesIO(data)) as zf_raw:
        assert zf_raw.namelist()[0] != name

    _extract_zip(data, tmp_path / "out")
    extracted = tmp_path / "out" / name
    assert extracted.is_file()
    assert extracted.read_bytes() == b"<html></html>"


def test_extract_zip_keeps_utf8_flagged_chinese(tmp_path: Path) -> None:
    """带 UTF-8 标记的中文 zip（Python 默认行为）解压后文件名正确，无副作用。"""
    name = "课件/首页.html"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(zipfile.ZipInfo(name), b"x")
    _extract_zip(buf.getvalue(), tmp_path / "out")
    assert (tmp_path / "out" / name).is_file()


def test_extract_zip_ascii_unaffected(tmp_path: Path) -> None:
    """ASCII 文件名解压正常。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("output/_manifest.json", b"{}")
    _extract_zip(buf.getvalue(), tmp_path / "out")
    assert (tmp_path / "out" / "output" / "_manifest.json").is_file()


def test_extract_zip_blocks_zip_slip(tmp_path: Path) -> None:
    """路径穿越仍被拦截（编码修正后仍做安全校验）。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(zipfile.ZipInfo("../evil.txt"), b"x")
    with pytest.raises(ValueError, match="zip-slip"):
        _extract_zip(buf.getvalue(), tmp_path / "out")


def test_extract_zip_rejects_oversize(tmp_path: Path) -> None:
    """解压总大小超限仍被拒绝（篡改 size 字段，避免真实分配大内存）。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(zipfile.ZipInfo("a.txt"), b"x")
    data = bytearray(buf.getvalue())
    # local file header uncompressed size @ +18；central directory @ +24
    for sig, off in ((b"PK\x03\x04", 18), (b"PK\x01\x02", 24)):
        j = data.find(sig)
        struct.pack_into("<I", data, j + off, 200 * 1024 * 1024)
    with pytest.raises(ValueError, match="100MB"):
        _extract_zip(bytes(data), tmp_path / "out")
