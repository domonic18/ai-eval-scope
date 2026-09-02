"""PackageToolServer — 场景包工程沙盒工具面（arch/15 §六）。

核心不变量：**磁盘上的包任何时刻只见过「用户确认且校验通过」的内容**——
写操作一律进暂存区（内存 dict），宿主在 diff 确认 + 校验门禁通过后经
:meth:`commit` 原子提交（staging → disk）。

读写分级（arch/15 §6.11.1，Claude Code 式文件工具机制）：
- **写**（write_file / delete_file）：硬沙盒——路径 ``resolve()`` 后必须位于包根内
  （防 ``..`` 与 symlink 逃逸），扩展名白名单 ``.yaml/.yml/.json/.md``，
  ``sut_configs/`` 凭证明文拒绝；无 shell、无网络、无包外写；
- **读**（read_file / list_files）分级授权：会话根内（暂存视图优先）→ 随包资源
  ``assets/``（自动授权只读）→ 外部路径经 ``ask_fn`` 向用户申请授权（拒绝即拉黑）；
  凭证类路径（密钥区 / sut_sessions / .env）一律硬拒，先于授权——凭证不回流 LLM 上下文。

工具实现为普通异步方法（可直接调用与测试，零框架依赖），经
``ToolExporterMixin`` 惰性导出为 LangChain Tool 绑定给 DeepAgents
（对齐 sut_tools.py 范式）。错误以 ``{"error": ...}`` 返回值交 Agent
自修复（tool_guard 精神：不中断图）。
"""

from __future__ import annotations

import difflib
import json
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any, ClassVar

from agent_eval.agent.tools import ToolExporterMixin, ToolSpec, truncate
from agent_eval.config.paths import PACKAGE_ROOT
from agent_eval.packages import MANIFEST_FILENAME

_WRITE_EXTS = {".yaml", ".yml", ".json", ".md"}
# sut_configs 凭证明文启发式：<field>: <非空且非 ${VAR} 引用的值>
_CRED_FIELD_RE = re.compile(
    r"^\s*(password|token|api_key|secret)\s*:\s*([^#\n]+?)\s*$", re.MULTILINE
)

# 随包发布资源根（自动授权只读域，arch/15 §6.11.1）：结构规范 / JSON Schema / 示例配置。
# 运行时资料禁止引用仓库 docs/ 路径（pip 安装用户没有 docs/）
_ASSETS_ROOT = PACKAGE_ROOT / "assets"
_LIST_MAX_FILES = 200

# 读取硬禁区（安全红线：凭证/token 不回流 LLM 上下文）——先于授权逻辑，用户同意也不可读：
# 密钥区 ~/.agent_eval/（platform/llm/sut_credentials 三文件）、SUT 会话 token、.env 键值
_CREDENTIAL_HINT_DIRS = {".agent_eval", "sut_sessions"}


def _is_credential_path(target: Path) -> bool:
    """凭证类路径判定：密钥区目录 / SUT 会话 token / .env（按约定名）。"""
    if target.name in (".env", "sut_credentials.json"):
        return True
    return any(part in _CREDENTIAL_HINT_DIRS for part in target.parts)


def _reference_notes() -> str:
    """内置包参照说明 + **真实文件树**（动态扫描）。

    给出实际清单而非示例名：Agent 按猜测路径 read_reference 失败时可直接
    从这里拿到正确的相对路径重试，避免放弃参照、凭记忆自创结构。
    """
    from agent_eval.packages import PackageManager

    lines = ["内置包参照（read_reference 的 ref 与 path 以此为准）："]
    for pkg in PackageManager().list(source="builtin"):
        files = sorted(p.relative_to(pkg.root).as_posix() for p in pkg.root.rglob("*.yaml"))
        lines.append(f"- {pkg.manifest.ref}（{len(files)} 个 yaml）: " + ", ".join(files))
    lines.append("read_reference 的 path 直接复制上面清单中的文件名（相对包根）")
    return "\n".join(lines)


def _is_credential_violation(content: str) -> str | None:
    """返回首个命中的凭证明文片段（None 表示干净）。``${VAR}`` 引用与空值放行。"""
    for match in _CRED_FIELD_RE.finditer(content):
        value = match.group(2).strip().strip("'\"")
        if not value or value.startswith("${"):
            continue
        if value.startswith("credential_ref"):
            continue
        return f"{match.group(1)}: {value[:12]}…"
    return None


class PackageToolServer(ToolExporterMixin):
    """场景包沙盒工具面（读写均过暂存区，宿主确认后才落盘）。"""

    TOOL_SPECS: ClassVar[list[ToolSpec]] = [
        ToolSpec(
            "list_files",
            "列出目录文件：会话根内（含暂存态标记 added/staged/deleted/unchanged）或"
            "随包资源 assets/；外部目录向用户申请授权后为普通清单",
            "list_files",
        ),
        ToolSpec(
            "read_file",
            "读取文件：会话根内（暂存版本优先）/ 随包资源 assets/（自动授权只读，"
            "如 guides/scenario-package-format.md 包结构规范）/ 外部路径（向用户申请授权）",
            "read_file",
        ),
        ToolSpec(
            "write_file",
            "写入/新建包内文件（进暂存区，落盘需宿主确认+校验通过）",
            "write_file",
        ),
        ToolSpec("delete_file", "删除包内文件（进暂存区）", "delete_file"),
        ToolSpec("read_manifest", "读取 agent_eval.yaml 包清单（暂存版本优先）", "read_manifest"),
        ToolSpec(
            "update_manifest",
            "浅合并更新包清单字段（如 version/labels/default_rule_set）",
            "update_manifest",
        ),
        ToolSpec(
            "validate_package",
            "校验暂存视图（清单合法 + 资源目录 + 规则 YAML 可解析），返回错误列表",
            "validate_package",
        ),
        ToolSpec(
            "search_reference",
            "检索内置包（chat/code/courseware）文件与场景扩展方法论要点",
            "search_reference",
        ),
        ToolSpec(
            "read_reference",
            "只读内置包文件内容（ref 如 chat；path 为包内相对路径）——参照真实格式，"
            "read_file 仅限本包",
            "read_reference",
        ),
        ToolSpec(
            "preview_diff",
            "预览暂存区 vs 磁盘原文的统一 diff（宿主确认界面同源）",
            "preview_diff",
        ),
    ]

    def __init__(
        self,
        pkg_root: Path,
        *,
        assets_root: Path | None = None,
        ask_fn: Any = None,  # async (question, *, options, secret) -> str（外部读取授权）
    ) -> None:
        self.root = Path(pkg_root).resolve()
        self.assets_root = (assets_root or _ASSETS_ROOT).resolve()
        self.ask_fn = ask_fn
        # 外部路径授权账本（host 边界同款：允许记账放行 / 拒绝拉黑防反复试探）
        self._granted: set[Path] = set()
        self._denied: set[Path] = set()
        # 暂存区：rel_path(POSIX) -> 新内容；None 表示删除
        self.staging: dict[str, str | None] = {}

    # ─── 沙盒与视图 ───────────────────────────────────────────────

    def _resolve_in(self, rel_path: str) -> Path:
        """把相对路径解析到包根内；越界（../、绝对、symlink 逃逸）抛 ValueError。"""
        target = (self.root / rel_path).resolve()
        if not target.is_relative_to(self.root):
            raise ValueError(f"路径越出包根（沙盒拒绝）: {rel_path}")
        return target

    def _disk_text(self, abs_path: Path) -> str | None:
        try:
            return abs_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None

    def _view(self) -> dict[str, str | None]:
        """磁盘视图 + 暂存覆盖（None = 已删除）的合并结果。"""
        view: dict[str, str | None] = {}
        if self.root.is_dir():
            for p in sorted(self.root.rglob("*")):
                if p.is_file() and ".git" not in p.parts:
                    view[p.relative_to(self.root).as_posix()] = self._disk_text(p)
        view.update(self.staging)
        return {k: v for k, v in view.items() if v is not None}

    def view(self) -> dict[str, str]:
        """暂存视图（宿主门禁读取：如 agent_protocol 通道必须经 probe_protocol 实测）。"""
        return self._view()

    # ─── 工具（Agent 可调用；错误以 {"error": ...} 返回） ─────────

    async def list_files(self, path: str = "") -> dict[str, Any]:
        """列目录文件（Claude Code 式分级，arch/15 §6.11.1）。

        会话根内（空/相对路径，含暂存态标记）与随包资源 assets/ 直接列出；
        其余外部目录复用 read_file 的授权账本（拒绝即拉黑）。
        """
        candidate = Path(path) if path else self.root
        target = (candidate if candidate.is_absolute() else self.root / candidate).resolve()
        if _is_credential_path(target):
            return {"error": f"安全红线：凭证类位置不可列（不回流 LLM 上下文）: {target}"}
        in_session = target == self.root or target.is_relative_to(self.root)
        in_assets = target == self.assets_root or target.is_relative_to(self.assets_root)
        if not (in_session or in_assets):
            err = await self._ensure_grant(target, listing=True)
            if err:
                return {"error": err}
        if in_session and target == self.root:
            return self._list_session()
        if not target.is_dir():
            return {"error": f"目录不存在: {target}"}
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

    async def read_file(self, path: str, max_chars: int = 8000) -> dict[str, Any]:
        """读文件（Claude Code 式分级授权，arch/15 §6.11.1）。

        会话根内（相对或根内绝对路径）→ 暂存视图优先；随包资源 assets/ → 自动授权
        只读；其余外部路径 → 经 ask_fn 向用户申请授权（拒绝即拉黑）。凭证路径一律
        硬拒（先于授权——红线：凭证/token 不回流 LLM 上下文）。
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
            else:
                content = self._disk_text(target)
                if content is None:
                    return {"error": f"文件不存在或不可读: {rel}"}
            return {"path": rel, "content": truncate(content, max_chars)}
        if target.is_relative_to(self.assets_root):
            return self._read_raw(target, max_chars)
        err = await self._ensure_grant(target)
        if err:
            return {"error": err}
        return self._read_raw(target, max_chars)

    def _read_raw(self, abs_path: Path, max_chars: int) -> dict[str, Any]:
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
            f"允许 Agent {verb}吗？（会话工作区之外）\n{target}",
            options=["允许", "拒绝"],
            secret=False,
        )
        if choice != "允许":
            self._denied.add(target)
            return f"用户拒绝{verb}: {target}"
        self._granted.add(target)
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

    async def read_manifest(self) -> dict[str, Any]:
        import yaml

        result = await self.read_file(MANIFEST_FILENAME)
        if "error" in result:
            return result
        try:
            data = yaml.safe_load(result["content"]) or {}
        except yaml.YAMLError as e:
            return {"error": f"清单 YAML 解析失败: {e}"}
        return {"manifest": data.get("package", data)}

    async def update_manifest(self, fields: dict[str, Any]) -> dict[str, Any]:
        import yaml

        current = await self.read_manifest()
        if "error" in current:
            return current
        merged = {**current["manifest"], **fields}
        content = "# 场景包清单（PackageAgent 更新）\npackage:\n" + yaml.safe_dump(
            merged, allow_unicode=True, sort_keys=False
        )
        return await self.write_file(MANIFEST_FILENAME, content)

    async def validate_package(self) -> dict[str, Any]:
        """对暂存视图做物化校验（清单合法 + 资源目录 + 规则 YAML 可解析）。"""
        import yaml

        from agent_eval.packages import load_manifest

        errors: list[str] = []
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            view = self._view()
            if not view:
                return {"ok": False, "errors": ["包视图为空（无文件）"]}
            for rel, content in view.items():
                if content is None:  # 空内容/删除标记：不落盘
                    continue
                dest = tmp_root / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(content, encoding="utf-8")
            if not (tmp_root / MANIFEST_FILENAME).is_file():
                return {"ok": False, "errors": [f"缺少清单 {MANIFEST_FILENAME}"]}
            try:
                load_manifest(tmp_root)
            except Exception as e:  # noqa: BLE001 — 校验错误收集后交 Agent 自修复
                errors.append(f"清单校验失败: {e}")
            for sub in ("rules", "prompts", "datasets"):
                if not (tmp_root / sub).is_dir() or not any((tmp_root / sub).iterdir()):
                    errors.append(f"缺少资源目录或为空: {sub}/")
            # 约定：rules/ 与 prompts/ 的资产是 YAML（13 配置管理）——只写 .md 会被
            # 下游加载器静默忽略（实测 Agent 曾把提示词写成 README 式 .md）
            for sub in ("rules", "prompts"):
                if (tmp_root / sub).is_dir() and not any((tmp_root / sub).glob("*.yaml")):
                    errors.append(f"{sub}/ 缺少 YAML 资产（提示词/规则集须为 .yaml）")
            for rf in sorted((tmp_root / "rules").glob("*.yaml")):
                try:
                    yaml.safe_load(rf.read_text(encoding="utf-8"))
                except yaml.YAMLError as e:
                    errors.append(f"规则 YAML 解析失败 {rf.name}: {e}")
        return {"ok": not errors, "errors": errors}

    async def search_reference(self, query: str) -> dict[str, Any]:
        """检索内置包（只读）匹配文件 + 方法论要点。"""
        from agent_eval.packages import PackageManager

        hits = []
        for pkg in PackageManager().list(source="builtin"):
            for p in sorted(pkg.root.rglob("*.yaml")):
                if query.lower() in p.relative_to(pkg.root).as_posix().lower():
                    hits.append(f"{pkg.manifest.ref}::{p.relative_to(pkg.root).as_posix()}")
        return {"query": query, "matched_files": hits[:20], "notes": _reference_notes()}

    async def read_reference(self, ref: str, path: str, max_chars: int = 6000) -> dict[str, Any]:
        """只读内置/本地缓存包的文件内容（Agent 参照真实格式的合法通道，免沙盒逃逸）。

        ref 走 PackageManager 解析（如 ``chat`` / ``courseware``）；path 限目标包根内。
        """
        from agent_eval.packages import PackageManager

        try:
            pkg = PackageManager().resolve_ref(ref)
        except Exception as e:  # noqa: BLE001 — 错误交 Agent 自修复
            return {"error": f"参考包不存在: {ref}（{e}；先 search_reference 检索可用包）"}
        available = sorted(p.relative_to(pkg.root).as_posix() for p in pkg.root.rglob("*.yaml"))
        try:
            target = (pkg.root / path).resolve()
            if not target.is_relative_to(pkg.root.resolve()):
                raise ValueError(f"路径越出参考包根: {path}")
            content = target.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            return {
                "error": f"文件不存在或不可读: {ref}::{path}（{e}）",
                "available_files": available,
                "hint": "path 请原样取 available_files 中的相对路径重试",
            }
        except ValueError as e:
            return {"error": str(e)}
        rel = target.relative_to(pkg.root.resolve()).as_posix()
        return {"package": pkg.manifest.ref, "path": rel, "content": truncate(content, max_chars)}

    async def preview_diff(self) -> dict[str, Any]:
        """暂存 vs 磁盘的统一 diff（与宿主确认界面同源）。"""
        return {"diff": self.render_diff(), "changed": len(self.staging)}

    # ─── 宿主侧（不经 Agent） ─────────────────────────────────────

    def render_diff(self) -> str:
        parts: list[str] = []
        for rel in sorted(self.staging):
            new = self.staging[rel]
            old = self._disk_text(self._resolve_in(rel)) if (self.root / rel).is_file() else None
            if new is None:
                parts.append(f"--- {rel}\n+++ /dev/null\n-（删除文件）")
                continue
            old_lines = (old or "").splitlines(keepends=True)
            new_lines = new.splitlines(keepends=True)
            diff = "".join(difflib.unified_diff(old_lines, new_lines, fromfile=rel, tofile=rel))
            parts.append(diff or f"{rel}（无变化）")
        return "\n".join(parts)

    def staged_manifest_id(self) -> str | None:
        """暂存视图中的清单 id（无清单/解析失败返回 None）——归位预告用。"""
        import yaml

        text = self._view().get(MANIFEST_FILENAME)
        if not text:
            return None
        try:
            data = yaml.safe_load(text) or {}
            return str((data.get("package") or {}).get("id") or "") or None
        except yaml.YAMLError:
            return None

    @property
    def has_staged_changes(self) -> bool:
        return bool(self.staging)

    def reset_staging(self) -> None:
        self.staging.clear()

    def commit(self) -> list[str]:
        """原子提交暂存到磁盘（宿主在确认+校验通过后调用），返回变更清单。"""
        changed: list[str] = []
        # 先全部物化到临时目录再原子替换内容，失败中途不产生半提交视图
        for rel, new in sorted(self.staging.items()):
            abs_path = self._resolve_in(rel)
            if new is None:
                if abs_path.is_file():
                    abs_path.unlink()
                changed.append(f"D {rel}")
                continue
            abs_path.parent.mkdir(parents=True, exist_ok=True)
            abs_path.write_text(new, encoding="utf-8")
            changed.append(f"M {rel}")
        self.staging.clear()
        return changed

    def export_staging_snapshot(self) -> str:
        """导出暂存快照 JSON（测试与日志用）。"""
        return json.dumps({"root": str(self.root), "staging": self.staging}, ensure_ascii=False)


def materialize_view(pkg_root: Path, server: PackageToolServer, dest: Path) -> Path:
    """把磁盘包 + 暂存覆盖物化到 dest（校验/测试辅助；不改动原包）。"""
    view = server._view()  # 宿主侧辅助（同包内）
    shutil.rmtree(dest, ignore_errors=True)
    for rel, content in view.items():
        if content is None:  # 空内容/删除标记：不落盘（rmtree 后即删除语义）
            continue
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return dest
