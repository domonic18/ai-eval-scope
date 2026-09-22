"""数据集域工具实现。

受控出网第二域：出网仅经 DatasetManager 单出口（HF/ModelScope SDK，域名
白名单随 source 结构性收窄）；写路径白名单仅 ``workspace/datasets/{name}/``
——工具不暴露 output/token 参数，红线由签名结构性保证而非运行时校验。

download_dataset 确认门槛照 run_eval 三段式：①非交互拒绝（ask_fn None →
refused，--trust-agent 不旁路）→ ③等价命令 + 来源 + 目标目录二选一（拒绝 →
DatasetManager 从未被调用）。下载编排复用 ``DatasetManager.download``
（与 CLI 同源真相源），经 to_thread 防阻塞事件循环。
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

MANIFEST_NAME = "_dataset_manifest.json"
_CONFIRM = "确认下载"


class DatasetContext:
    """数据集域共享状态（与 ExecContext 同构最小集）。"""

    def __init__(
        self,
        *,
        ask_fn: Any = None,  # async (question, *, options, secret) -> str | None
        workspace_root: Path | None = None,
        log_path: Path | None = None,
    ) -> None:
        self.ask_fn = ask_fn
        self.workspace_root = workspace_root
        self.log_path = log_path

    @property
    def datasets_dir(self) -> Path | None:
        """下载落盘根（workspace/datasets/）；无 workspace 时 None。"""
        return self.workspace_root / "datasets" if self.workspace_root else None

    def log(self, tool: str, **payload: Any) -> None:
        """jsonl 事件账本（格式同 ExecContext.log；log_path 为空则 no-op）。"""
        if self.log_path is None:
            return
        import time

        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        entry = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "tool": tool, **payload}
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")


def _dir_size(path: Path) -> int:
    """目录字节总量（回执数据规模）。"""
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def _scan_local(datasets_dir: Path | None) -> dict[str, dict[str, Any]]:
    """扫描已下载数据集（manifest 键 = 目录名），值含路径与下载时间。"""
    if datasets_dir is None or not datasets_dir.is_dir():
        return {}
    local: dict[str, dict[str, Any]] = {}
    for manifest in sorted(datasets_dir.glob(f"*/{MANIFEST_NAME}")):
        try:
            meta = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            meta = {}
        local[manifest.parent.name] = {
            "local_path": str(manifest.parent),
            "downloaded_at": meta.get("downloaded_at"),
            "repo_id": meta.get("repo_id"),
            "source": meta.get("source"),
        }
    return local


class ListDatasetsTool:
    """list_datasets：索引清单 + 本地已下载状态配对（只读，不出网）。"""

    def __init__(self, ctx: DatasetContext) -> None:
        self.ctx = ctx

    async def list_datasets(self) -> dict[str, Any]:
        from agent_eval.datasets import list_datasets as registry_list

        local = _scan_local(self.ctx.datasets_dir)
        items: list[dict[str, Any]] = []
        for entry in registry_list().values():
            dir_name = (entry.get_id(entry.default_source) or entry.id).rsplit("/", 1)[-1]
            hit = local.pop(dir_name, None) or local.pop(entry.id, None)
            items.append(
                {
                    "id": entry.id,
                    "name": entry.name,
                    "category": entry.category,
                    "default_source": entry.default_source,
                    "hf_id": entry.hf_id,
                    "ms_id": entry.ms_id,
                    "description": entry.description,
                    "downloaded": hit is not None,
                    "local_path": (hit or {}).get("local_path"),
                    "downloaded_at": (hit or {}).get("downloaded_at"),
                }
            )
        # 本地目录里还有索引外的下载（用户手动 repo id 下载）——如实列出
        for dir_name, hit in local.items():
            items.append(
                {
                    "id": dir_name,
                    "name": dir_name,
                    "category": "",
                    "default_source": hit.get("source") or "",
                    "hf_id": "",
                    "ms_id": "",
                    "description": "(索引外：按完整 repo id 下载)",
                    "downloaded": True,
                    "local_path": hit.get("local_path"),
                    "downloaded_at": hit.get("downloaded_at"),
                }
            )
        self.ctx.log("list_datasets", total=len(items))
        return {"status": "done", "total": len(items), "datasets": items}


class DownloadTool:
    """download_dataset：确认门槛 + DatasetManager 编排复用（受控出网）。"""

    def __init__(self, ctx: DatasetContext) -> None:
        self.ctx = ctx

    async def download_dataset(
        self,
        name: str,
        source: str = "",
        revision: str = "",
        force: bool = False,
    ) -> dict[str, Any]:
        # ① 非交互拒绝（唯一旁路拒绝点）：确认是下载的前置语义，无确认通道即不执行
        if self.ctx.ask_fn is None:
            return {
                "status": "refused",
                "reason": "非交互环境（--yes/CI）不支持会话内下载数据集——请用等价 CLI 命令",
            }

        # ③ 确认门槛：等价命令 + 来源 repo + 目标目录 + 已存在提示，二选一
        from agent_eval.cli.console.equiv import dataset_argv, render
        from agent_eval.datasets import lookup
        from agent_eval.datasets.registry import DatasetEntry

        entry = lookup(name)
        if entry is None:
            entry = DatasetEntry(
                id=name, name=name, hf_id=name, ms_id=name, description="(用户指定 repo id)"
            )
        target_dir = (self.ctx.datasets_dir or Path("workspace/datasets")) / name
        exists = target_dir.exists() and any(target_dir.iterdir())
        argv = dataset_argv(
            name,
            source=source or None,
            revision=revision or None,
            force=force or None,
        )
        source_line = (
            f"来源：默认源 {entry.default_source}"
            f"（HuggingFace: {entry.hf_id or '—'} / ModelScope: {entry.ms_id or '—'}）"
        )
        exists_line = (
            "\n注意：目标目录已存在且非空——不传 force 将跳过下载，传 force 会清空重下"
            if exists
            else ""
        )
        answer = await self.ctx.ask_fn(
            f"将下载数据集（等价命令，进度将直出本终端）：\n  {render(argv)}\n"
            f"{source_line}\n落盘：{target_dir}/{exists_line}\n确认下载？",
            options=[_CONFIRM, "取消"],
            secret=False,
        )
        if answer != _CONFIRM:
            self.ctx.log("download_dataset", confirmed=False, name=name)
            return {"status": "declined", "equivalent_command": render(argv)}

        # ④ 下载编排：与 CLI 同源 DatasetManager；不传 output/token——写白名单与
        #    token 红线由签名结构性保证；to_thread 防 HF/MS SDK 阻塞事件循环
        from agent_eval.datasets import DatasetManager

        def _download() -> Path:
            return DatasetManager().download(
                name,
                source=source or None,
                revision=revision or None,
                force=force,
            )

        try:
            target = await asyncio.to_thread(_download)
        except Exception as exc:  # noqa: BLE001 — 字段化失败回执（下载器异常不打穿会话图）
            self.ctx.log("download_dataset", ok=False, name=name, error=str(exc))
            return {"status": "failed", "error": str(exc), "dataset": name}

        manifest_path = target / MANIFEST_NAME
        try:
            meta = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            meta = {}
        self.ctx.log("download_dataset", ok=True, name=name)
        return {
            "status": "done",
            "dataset": name,
            "source": meta.get("source"),
            "repo_id": meta.get("repo_id"),
            "dataset_dir": str(target),
            "manifest_path": str(manifest_path),
            "size_bytes": _dir_size(target),
            "already_existed": exists and not force,
        }
