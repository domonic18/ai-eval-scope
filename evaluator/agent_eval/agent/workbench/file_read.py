"""格式感知文件读取 — 结构化格式分派原语。

``read_file`` 的底层能力：按扩展名把常见数据格式（parquet/CSV/JSONL/JSON/
zip）解析为「列名 + 行数 + 样本行」的结构化视图，文本类回落调用方原文读取。
数据集落盘（HF parquet / 开源 CSV）、run 产物、任意本地表格数据共用同一
读取原语——工具面不随格式清单增长（系统性能力，非逐格式打补丁）。

pyarrow 惰性导入（datasets extra），未装抛带安装指引的 ValueError。
样本值统一截断（防单值超长刷爆会话上下文）；样本行数夹取 1-20。
所有异常规范为 ValueError（调用方转 ``{"error": ...}`` 交 Agent 自修复）。
"""

from __future__ import annotations

import csv
import json
import zipfile
from pathlib import Path
from typing import Any

__all__ = ["clip_value", "is_structured", "read_structured"]

_LIMIT_MAX = 20
_VALUE_CHARS = 300  # 单值截断（嵌套结构内同样生效）
_ZIP_ENTRIES = 20

_SUFFIX_FORMATS = {
    ".parquet": "parquet",
    ".csv": "csv",
    ".jsonl": "jsonl",
    ".ndjson": "jsonl",
    ".json": "json",
    ".zip": "zip",
}


def is_structured(path: Path) -> bool:
    """该路径是否属于本原语可结构化解析的格式。"""
    return path.suffix.lower() in _SUFFIX_FORMATS


def clip_value(value: Any, chars: int = _VALUE_CHARS) -> Any:
    """递归截断样本值里的超长字符串 / 超大容器（样本行防刷爆上下文）。"""
    if isinstance(value, str) and len(value) > chars:
        return value[:chars] + f"…(共{len(value)}字符)"
    if isinstance(value, list):
        return [clip_value(v) for v in value[:20]]
    if isinstance(value, dict):
        return {k: clip_value(v) for k, v in list(value.items())[:20]}
    return value


def read_structured(path: Path, limit: int) -> dict[str, Any]:
    """结构化格式读取：``{format, columns?, row_count?, sample_rows?/entries?}``。

    解析失败 / 格式不支持 / pyarrow 未装一律抛 ValueError（带可解释原因）。
    大文件安全：parquet 只读首个 batch，CSV/JSONL 只读前 limit 行——全量
    解析发生在调用方明确要求之前不存在。
    """
    limit = max(1, min(_LIMIT_MAX, int(limit)))
    reader = {
        ".parquet": _read_parquet,
        ".csv": _read_csv,
        ".jsonl": _read_jsonl,
        ".ndjson": _read_jsonl,
        ".json": _read_json,
        ".zip": _read_zip,
    }.get(path.suffix.lower())
    if reader is None:
        raise ValueError(f"非结构化格式，无法解析: {path.suffix}")
    try:
        return reader(path, limit)
    except ValueError:
        raise
    except Exception as exc:  # noqa: BLE001 — 异常规范为 ValueError（统一 error 回执通道）
        raise ValueError(f"结构化解析失败（{path.suffix}）: {exc}") from exc


def _read_parquet(path: Path, limit: int) -> dict[str, Any]:
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise ValueError(
            "读取 parquet 需要 pyarrow——请先安装数据集依赖: uv sync --extra datasets"
        ) from exc
    pf = pq.ParquetFile(path)
    columns = [n for n in pf.schema_arrow.names if not n.startswith("__index")]
    batch = next(pf.iter_batches(batch_size=limit), None)
    rows = batch.to_pylist() if batch is not None else []
    sample = [
        {k: v for k, v in row.items() if not k.startswith("__index")}
        for row in rows
        if isinstance(row, dict)
    ]
    return {
        "format": "parquet",
        "columns": columns,
        "row_count": pf.metadata.num_rows,
        "sample_rows": [clip_value(r) for r in sample],
    }


def _read_csv(path: Path, limit: int) -> dict[str, Any]:
    with path.open("r", encoding="utf-8", errors="replace", newline="") as f:
        reader = csv.DictReader(f)
        columns = list(reader.fieldnames or [])
        rows = [clip_value(row) for _, row in zip(range(limit), reader)]
    return {"format": "csv", "columns": columns, "sample_rows": rows}


def _read_jsonl(path: Path, limit: int) -> dict[str, Any]:
    rows: list[Any] = []
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(clip_value(json.loads(line)))
            if len(rows) >= limit:
                break
    return {"format": "jsonl", "sample_rows": rows}


def _read_json(path: Path, limit: int) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    if isinstance(data, list):
        return {
            "format": "json",
            "item_count": len(data),
            "sample_rows": [clip_value(item) for item in data[:limit]],
        }
    return {"format": "json", "sample_rows": [clip_value(data)]}


def _read_zip(path: Path, limit: int) -> dict[str, Any]:  # noqa: ARG001 — 分派签名统一
    with zipfile.ZipFile(path) as zf:
        names = [info.filename for info in zf.infolist() if not info.is_dir()]
    return {"format": "zip", "entry_count": len(names), "entries": names[:_ZIP_ENTRIES]}
