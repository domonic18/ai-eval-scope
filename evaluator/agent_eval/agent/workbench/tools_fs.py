"""PackageToolServer 文件工具 mixin — list/read/write/delete（分级授权 + 格式感知）。

Agent 可调用；错误以 ``{"error": ...}`` 返回值交 Agent 自修复（不中断图）。
仅供 ``tools.PackageToolServer`` 组合，不独立使用。
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from agent_eval.agent.core.tools import truncate
from agent_eval.agent.workbench.tools_shared import (
    _DEFAULT_READ_CHARS,
    _LIST_MAX_FILES,
    _WRITE_EXTS,
    _is_credential_path,
    _is_credential_violation,
)


class FileToolsMixin:
    """文件四工具 + 外部路径授权门（组合用 mixin）。"""

    # 组合主体成员声明（仅注解，零运行时）——供类型检查器解析 self.* 引用
    root: Path
    staging: dict[str, str | None]
    assets_root: Path
    workspace_root: Path | None
    ask_fn: Any
    _granted: set[Path]
    _denied: set[Path]
    _is_auto_read: Callable[..., bool]
    _resolve_in: Callable[..., Path]
    _disk_text: Callable[..., str | None]

    async def list_files(self, path: str = "") -> dict[str, Any]:
        """列目录文件（分级授权）。

        会话根内（空/相对路径，含暂存态标记）、随包资源 assets/ 与运行产物区
        workspace/ 直接列出；其余外部目录复用 read_file 的授权账本（拒绝即拉黑）。
        """
        candidate = Path(path) if path else self.root
        target = (candidate if candidate.is_absolute() else self.root / candidate).resolve()
        if _is_credential_path(target):
            return {"error": f"安全红线：凭证类位置不可列（不回流 LLM 上下文）: {target}"}
        in_session = target == self.root
        if not self._is_auto_read(target):
            err = await self._ensure_grant(target, listing=True)
            if err:
                return {"error": err}
        if in_session:
            return self._list_session()
        if not target.is_dir():
            return {"error": f"不是目录或不存在: {target}"}
        files = sorted(
            p.relative_to(target).as_posix()
            for p in target.rglob("*")
            if p.is_file() and ".git" not in p.parts and not _is_credential_path(p)
        )
        listed = files[:_LIST_MAX_FILES]
        result: dict[str, Any] = {"root": str(target), "files": listed, "total": len(files)}
        if len(files) > len(listed):
            result["truncated"] = True
        return result

    def _list_session(self) -> dict[str, Any]:
        """会话根清单（含暂存状态标记）。"""
        staged = set(self.staging)
        on_disk = (
            {
                p.relative_to(self.root).as_posix()
                for p in self.root.rglob("*")
                if p.is_file() and ".git" not in p.parts
            }
            if self.root.is_dir()
            else set()
        )
        files = []
        for rel in sorted(on_disk | staged):
            if rel in self.staging:
                if self.staging[rel] is None:
                    files.append({"path": rel, "status": "deleted"})
                elif rel in on_disk:
                    files.append({"path": rel, "status": "staged"})
                else:
                    files.append({"path": rel, "status": "added"})
            else:
                files.append({"path": rel, "status": "unchanged"})
        return {"files": files, "root": str(self.root)}

    async def read_file(
        self,
        path: str,
        max_chars: int = _DEFAULT_READ_CHARS,
        limit: int = 5,
    ) -> dict[str, Any]:
        """读文件（分级授权 + 格式感知）。

        会话根内（相对或根内绝对路径）→ 暂存视图优先；assets/ 与 workspace/ →
        自动授权只读；其余外部路径 → 经 ask_fn 向用户申请授权（拒绝即拉黑）。
        凭证路径一律硬拒（先于授权——红线：凭证/token 不回流 LLM 上下文）。
        结构化格式（parquet/CSV/JSONL/JSON/zip）解析为列名 + 样本行（limit），
        文本类返回截断原文（max_chars）。
        """
        candidate = Path(path)
        target = (candidate if candidate.is_absolute() else self.root / candidate).resolve()
        if _is_credential_path(target):
            return {"error": f"安全红线：凭证类文件不可读（不回流 LLM 上下文）: {target}"}
        if target.is_relative_to(self.root):
            rel = target.relative_to(self.root).as_posix()
            if rel in self.staging:
                content = self.staging[rel]
                if content is None:
                    return {"error": f"文件已在暂存区标记删除: {rel}"}
                return {"path": rel, "content": truncate(content, max_chars)}
            # 磁盘数据文件同享格式解析（包内 datasets/*.csv|parquet 与外部一致）
            from agent_eval.agent.workbench.file_read import is_structured

            if is_structured(target):
                return self._read_raw(target, max_chars, limit)
            content = self._disk_text(target)
            if content is None:
                return {"error": f"文件不存在或不可读: {rel}"}
            return {"path": rel, "content": truncate(content, max_chars)}
        if not self._is_auto_read(target):
            err = await self._ensure_grant(target)
            if err:
                return {"error": err}
        return self._read_raw(target, max_chars, limit)

    def _read_raw(self, abs_path: Path, max_chars: int, limit: int = 5) -> dict[str, Any]:
        """磁盘原文 / 结构化视图读取（自动授权域与已授权外部路径共用）。"""
        from agent_eval.agent.workbench.file_read import is_structured, read_structured

        if is_structured(abs_path):
            try:
                return {"path": str(abs_path), **read_structured(abs_path, limit)}
            except ValueError as e:
                return {"error": f"{abs_path}: {e}"}
        try:
            content = abs_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            return {"error": f"文件不存在或不可读: {abs_path}（{e}）"}
        return {"path": str(abs_path), "content": truncate(content, max_chars)}

    async def _ensure_grant(self, target: Path, *, listing: bool = False) -> str | None:
        """外部路径授权门（host 边界同款：允许记账放行 / 拒绝拉黑）。None = 放行。"""
        for denied in (*self._denied,):
            if target == denied or target.is_relative_to(denied):
                return f"该路径此前已被用户拒绝，勿再试探: {target}"
        for granted in (*self._granted,):
            if target == granted or target.is_relative_to(granted):
                return None
        if self.ask_fn is None:
            return (
                f"会话根外的路径需用户授权{'列出' if listing else '读取'}: {target}"
                "（当前无交互通道——请把文件放入会话根目录后重试）"
            )
        verb = "列出目录" if listing else "读取文件"
        choice = await self.ask_fn(
            f"允许 Agent {verb}吗？（会话工作区与运行产物区之外；"
            f"允许后本会话内该目录含子目录不再询问）\n{target}",
            options=["允许", "拒绝"],
            secret=False,
        )
        if choice != "允许":
            self._denied.add(target)
            return f"用户拒绝{verb}: {target}"
        # 授权记账提升到所在目录（问句承诺「该目录含子目录不再询问」）——按文件
        # 精确记账曾让同目录兄弟文件再次弹窗；拒绝保持精确路径拉黑（不扩大化）
        self._granted.add(target if target.is_dir() else target.parent)
        return None

    async def write_file(self, path: str, content: str) -> dict[str, Any]:
        if Path(path).suffix not in _WRITE_EXTS:
            return {"error": f"扩展名不在白名单 {_WRITE_EXTS}: {path}"}
        try:
            abs_path = self._resolve_in(path)
        except ValueError as e:
            return {"error": str(e)}
        rel = abs_path.relative_to(self.root).as_posix()
        if rel.startswith("sut_configs/"):
            hit = _is_credential_violation(content)
            if hit:
                return {
                    "error": (
                        f"安全红线：sut_configs 禁止凭证明文（命中 {hit}）。"
                        "凭证经 credential_ref 引用，明文请录 agent-eval secrets set <ref>.<field>"
                    )
                }
        # YAML fail-fast 预检：截断/损坏内容当场打回（垃圾进不了暂存，省掉
        # 「靠 Agent read_file 自检才发现截断」的一整轮——实测事故）。update_manifest
        # 经此天然受益；sut_configs 的 schema 校验由 write_sut_config 另行负责
        if Path(path).suffix in (".yaml", ".yml"):
            import yaml

            try:
                yaml.safe_load(content)
            except yaml.YAMLError as e:
                return {
                    "error": (
                        f"YAML 解析失败（未入暂存区）{rel}: {e}——内容疑似被截断"
                        "或损坏，请整体重写完整文件"
                    )
                }
        self.staging[rel] = content
        return {"ok": True, "staged": rel, "note": "已入暂存区，落盘需宿主确认+校验通过"}

    async def delete_file(self, path: str) -> dict[str, Any]:
        try:
            abs_path = self._resolve_in(path)
        except ValueError as e:
            return {"error": str(e)}
        rel = abs_path.relative_to(self.root).as_posix()
        if rel not in self.staging and not abs_path.is_file():
            return {"error": f"文件不存在: {rel}"}
        self.staging[rel] = None
        return {"ok": True, "staged_delete": rel}
