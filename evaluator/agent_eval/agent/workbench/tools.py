"""PackageToolServer — 场景包工程沙盒工具面。

核心不变量：**磁盘上的包任何时刻只见过「用户确认且校验通过」的内容**——
写操作一律进暂存区（内存 dict），宿主在 diff 确认 + 校验门禁通过后经
:meth:`commit` 原子提交（staging → disk）。

读写分级（Claude Code 式文件工具机制）：
- **写**（write_file / delete_file）：硬沙盒——路径 ``resolve()`` 后必须位于包根内
  （防 ``..`` 与 symlink 逃逸），扩展名白名单 ``.yaml/.yml/.json/.md``，
  ``sut_configs/`` 凭证明文拒绝；无 shell、无网络、无包外写；
- **读**（read_file / list_files）分级授权：会话根内（暂存视图优先）→ 随包资源
  ``assets/`` 与运行产物区 ``workspace/``（自动授权只读——读自己的产物不弹窗，
  v4.14）→ 外部路径经 ``ask_fn`` 向用户申请授权（拒绝即拉黑，允许按目录记账
  含子目录）；
  凭证类路径（密钥区 / sut_sessions / .env）一律硬拒，先于授权——凭证不回流 LLM 上下文。
- **读的格式感知**（v4.14）：read_file 按扩展名分派——parquet/CSV/JSONL/JSON/
  zip 解析为「列名 + 行数 + 样本行」结构化视图（:mod:`file_read` 原语），
  文本类返回截断原文；数据集/run 产物等任意本地数据共用同一读取能力。

工具实现为普通异步方法（可直接调用与测试，零框架依赖），经
``ToolExporterMixin`` 惰性导出为 LangChain Tool 绑定给 DeepAgents
（对齐 sut_tools.py 范式）。错误以 ``{"error": ...}`` 返回值交 Agent
自修复（tool_guard 精神：不中断图）。

组合结构（按职责拆分，均 <300 行）：
- ``tool_specs``：TOOL_SPECS 规格（Agent 侧工具文档）
- ``tools_shared``：共享常量与纯函数（凭证红线 / 骨架门禁 / 截断缺省）
- ``tools_sandbox``：沙盒路径解析 + 暂存视图 + 骨架回填（服务端侧）
- ``tools_fs``：文件四工具 + 外部路径授权门
- ``tools_manifest``：清单读写 + SUT 配置物化 + 暂存视图校验
- ``tools_packages``：跨包参照 / 原位编辑切换 / 评估器真相源 / diff 预览
- 本模块：组合主体（``__init__`` 状态 + 宿主侧提交面）+ ``materialize_view``
"""

from __future__ import annotations

import difflib
import shutil
from pathlib import Path
from typing import Any

from agent_eval.agent.core.tools import ToolExporterMixin, ToolSpec
from agent_eval.agent.workbench.tool_specs import TOOL_SPECS as _PACKAGE_TOOL_SPECS
from agent_eval.agent.workbench.tools_fs import FileToolsMixin
from agent_eval.agent.workbench.tools_manifest import ManifestToolsMixin
from agent_eval.agent.workbench.tools_packages import PackageRefToolsMixin
from agent_eval.agent.workbench.tools_sandbox import SandboxViewMixin
from agent_eval.agent.workbench.tools_shared import (
    _ASSETS_ROOT,
    SKELETON_FILENAME,
)
from agent_eval.packages import MANIFEST_FILENAME


class PackageToolServer(
    SandboxViewMixin,
    FileToolsMixin,
    ManifestToolsMixin,
    PackageRefToolsMixin,
    ToolExporterMixin,
):
    """场景包沙盒工具面（读写均过暂存区，宿主确认后才落盘）。"""

    # 与基类同形态（非 ClassVar）：ClassVar 遮蔽实例变量声明会被 mypy 拒绝
    TOOL_SPECS: list[ToolSpec] = _PACKAGE_TOOL_SPECS

    def __init__(
        self,
        pkg_root: Path,
        *,
        assets_root: Path | None = None,
        ask_fn: Any = None,  # async (question, *, options, secret) -> str（外部读取授权）
        workspace_root: Path | None = None,  # 运行产物区（自动授权只读域，v4.14）
    ) -> None:
        self.root = Path(pkg_root).resolve()
        self.assets_root = (assets_root or _ASSETS_ROOT).resolve()
        self.workspace_root = Path(workspace_root).resolve() if workspace_root else None
        self.ask_fn = ask_fn
        # 外部路径授权账本（host 边界同款：允许记账放行 / 拒绝拉黑防反复试探）
        self._granted: set[Path] = set()
        self._denied: set[Path] = set()
        # 暂存区：rel_path(POSIX) -> 新内容；None 表示删除
        self.staging: dict[str, str | None] = {}
        # 创建骨架（过程产物，commit 排除出包）的最新完整文本——宿主归档为审计
        # 产物用；同时是跨轮暂存清除后 fact_sink 续写的种子（见 _skeleton_text）
        self.skeleton_archive: str | None = None
        # 探测证据账本（SUTProbeToolServer，agent.py 装配后绑定——两 server 构造
        # 互需对方能力，靠后绑定解环）：write_sut_config 机械注入 auth 的事实源
        self.ledger: Any = None
        # 会话目标切换钩子（agent.relocate_root，agent.py 构造后注入——与 ledger
        # 同风格解环）：edit_package 的切根执行体；None=工具不可用（防御）
        self.relocate_fn: Any = None

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
        """原子提交暂存到磁盘（宿主在确认+校验通过后调用），返回变更清单。

        SKELETON.md 排除在外：骨架是过程产物（探测事实与证据链），落进包根会随
        归位混入最终包——从暂存摘除，最新文本留在 :attr:`skeleton_archive` 供宿主
        归档为审计产物（WorkbenchAgent 落会话区）。
        """
        changed: list[str] = []
        # 先全部物化到临时目录再原子替换内容，失败中途不产生半提交视图
        for rel, new in sorted(self.staging.items()):
            if rel == SKELETON_FILENAME:
                self.staging.pop(rel)
                self.skeleton_archive = new
                changed.append(f"S {rel}（骨架：过程产物不入包，已留档）")
                continue
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

    def export_staging_snapshot(self) -> dict[str, Any]:
        """导出进度快照（跨进程续作源，SessionStore 每轮随写）。

        只含可序列化的进度态：暂存文件文本 + 骨架留档（commit 摘除前不可丢）。
        不含凭证域——探测账本的 session_tokens 等凭证态由 SUTProbeToolServer
        .ledger_snapshot 另行导出，且同样只含事实（无凭证值）。
        """
        return {
            "root": str(self.root),
            "staging": self.staging,
            "skeleton_archive": self.skeleton_archive,
        }

    def import_staging_snapshot(self, payload: Any) -> int:
        """恢复暂存与骨架留档，返回恢复的暂存条数（类型不符静默忽略单条）。

        skeleton_archive 仅在当前为空时采纳——本会话已更新的留档优先。
        """
        if not isinstance(payload, dict):
            return 0
        staging = payload.get("staging")
        if isinstance(staging, dict):
            self.staging = {
                rel: content
                for rel, content in staging.items()
                if isinstance(rel, str) and (content is None or isinstance(content, str))
            }
        if self.skeleton_archive is None and isinstance(payload.get("skeleton_archive"), str):
            self.skeleton_archive = payload["skeleton_archive"]
        return len(self.staging)


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
