"""PackageToolServer 沙盒基础设施 mixin — 路径解析 / 暂存视图 / 创建骨架。

服务端侧（不经 Agent）：写域边界解析、磁盘+暂存合并视图、骨架事实回填。
仅供 ``tools.PackageToolServer`` 组合（实例状态由组合主体 ``__init__`` 建立），
不独立使用。
"""

from __future__ import annotations

from pathlib import Path
from typing import cast

from agent_eval.agent.workbench.tools_shared import (
    _MECHANICAL_SECTION,
    SKELETON_FILENAME,
)


class SandboxViewMixin:
    """沙盒路径解析 + 暂存视图 + 骨架回填（组合用 mixin）。"""

    # 组合主体成员声明（仅注解，零运行时）——供类型检查器解析 self.* 引用
    root: Path
    staging: dict[str, str | None]
    skeleton_archive: str | None
    assets_root: Path
    workspace_root: Path | None

    def _is_auto_read(self, target: Path) -> bool:
        """自动授权只读域判定：会话根 / 随包资源 / 运行产物区 workspace/。

        workspace 是本系统自己的运行产物根（数据集、run 产物、会话日志）——
        读自己的产物不弹授权（v4.14：曾对 datasets 逐目录弹窗，用户一次任务
        被问 4 次）；凭证红线（``_is_credential_path``）在调用方先于本判定。
        """
        if target == self.root or target.is_relative_to(self.root):
            return True
        if target == self.assets_root or target.is_relative_to(self.assets_root):
            return True
        return self.workspace_root is not None and (
            target == self.workspace_root or target.is_relative_to(self.workspace_root)
        )

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

    def _view(self) -> dict[str, str]:
        """磁盘视图 + 暂存覆盖的合并结果（None = 已删除的文件被过滤）。"""
        view: dict[str, str | None] = {}
        if self.root.is_dir():
            for p in sorted(self.root.rglob("*")):
                if p.is_file() and ".git" not in p.parts:
                    view[p.relative_to(self.root).as_posix()] = self._disk_text(p)
        view.update(self.staging)
        return cast(dict[str, str], {k: v for k, v in view.items() if v is not None})

    def view(self) -> dict[str, str]:
        """暂存视图（宿主门禁读取：如 agent_protocol 通道必须经 probe_protocol 实测）。"""
        return self._view()

    def disk_text(self, rel_path: str) -> str | None:
        """磁盘原文（不含暂存覆盖）——落盘对账门禁的基线读取口。

        与 :meth:`read_file`（分级授权、暂存优先、截断）不同：这是机械通道，
        仅供门禁取「此前已落盘放行」的基线内容；越界/缺失/不可读一律 None
        （保守侧：无基线 = 全量对账）。
        """
        try:
            return self._disk_text(self._resolve_in(rel_path))
        except ValueError:
            return None

    def rebind_root(self, new_root: Path) -> None:
        """重绑包根（包归位后调用）：后续读写/diff/门禁以新位置为准。

        会话中重定向沙盒零状态残留——staging 是内存 dict、root 无其它持久句柄，
        _resolve_in/_view/commit 均按 self.root 现取；调用时机（commit 之后，staging
        已清）保证无跨根脏暂存。
        """
        self.root = Path(new_root).resolve()

    # ─── 创建骨架（Plan-as-Artifact：服务端事实回填 + 开槽门禁） ───

    def _skeleton_text(self) -> str | None:
        """骨架当前文本：暂存优先，磁盘兜底，再兜底跨轮归档文本；无则 None。"""
        if (staged := self.staging.get(SKELETON_FILENAME)) is not None:
            return staged
        if SKELETON_FILENAME in self.staging:
            return None  # 暂存标记删除：以删除为准
        return self._disk_text(self.root / SKELETON_FILENAME) or self.skeleton_archive

    def append_skeleton_fact(self, fact_line: str) -> None:
        """探测验证成功的事实机械回填骨架（fact_sink 回调目标，非 Agent 工具）。

        事实行由探测工具服务端写就（不经 LLM 转述——验证结论到骨架的传递零变形），
        追加进「机械实测事实」节（无则在文末创建）；Agent 据此把对应开槽改写闭合。
        无骨架时静默忽略（骨架 opt-in：克隆/fork 既有包的会话不受影响）；
        回填失败不抛（事实sink 故障不阻断探测结论本身）。
        """
        text = self._skeleton_text()
        if text is None:
            return
        entry = f"- [x] {fact_line.strip()}"
        header = _MECHANICAL_SECTION + "\n"
        if header in text:
            head, _, tail = text.partition(header)
            new_text = head + header + entry + "\n" + tail
        else:
            new_text = text.rstrip("\n") + f"\n\n{_MECHANICAL_SECTION}\n{entry}\n"
        self.staging[SKELETON_FILENAME] = new_text
