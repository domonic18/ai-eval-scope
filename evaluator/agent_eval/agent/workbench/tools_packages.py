"""PackageToolServer 包参照工具 mixin — list_packages/edit_package/参照读取/评估器清单/preview_diff。

Agent 可调用；错误以 ``{"error": ...}`` 返回值交 Agent 自修复（不中断图）。
仅供 ``tools.PackageToolServer`` 组合，不独立使用。
"""

from __future__ import annotations

import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from agent_eval.agent.core.tools import truncate
from agent_eval.agent.workbench.tools_shared import (
    _DEFAULT_REFERENCE_CHARS,
    _reference_notes,
)
from agent_eval.packages import MANIFEST_FILENAME


class PackageRefToolsMixin:
    """跨包参照（三源发现 / 只读参照 / 评估器真相源）+ 原位编辑切换（组合用 mixin）。"""

    # 组合主体成员声明（仅注解，零运行时）——供类型检查器解析 self.* 引用
    root: Path
    staging: dict[str, str | None]
    skeleton_archive: str | None
    ask_fn: Any
    relocate_fn: Any
    _granted: set[Path]
    _denied: set[Path]
    render_diff: Callable[..., str]

    async def list_packages(self, source: str = "") -> dict[str, Any]:
        """列出全部已发现场景包（builtin/local/project 三源，PackageManager 同源发现）。

        「当前有哪些包」的机械真相源（与 CLI ``scenario list``、执行域选包同一
        枚举）——项目根（cwd）一级子目录含 agent_eval.yaml 的都算 project 包。
        只读无授权需求：包根 path 是发现元数据，读包内文件仍走分级授权
        （read_reference 按 ref 直读 / read_file 外部路径申请授权）。
        """
        from agent_eval.packages import PackageManager

        if source and source not in ("builtin", "local", "project"):
            return {"error": f"未知 source: {source}（可选 builtin / local / project，缺省全部）"}
        packages = [
            {
                "ref": pkg.manifest.ref,
                "source": pkg.source,
                "path": str(pkg.root),
                "name": pkg.manifest.name,
                "version": pkg.manifest.version,
                "description": truncate(pkg.manifest.description, 80),
                "editable": pkg.source != "builtin",
            }
            for pkg in PackageManager().list(source=source or None)
        ]
        notes = (
            "改已有 project/local 包（加/改/删用例、调规则、修 sut_config 等轻量修改）："
            "会话内直接 edit_package(ref) 原位编辑——用户确认后切根生效，无需退出会话、"
            "无需骨架。fork 改造仅限明确要新版本/新包（换新 scenario/id）。builtin 只读。"
            "读任意包内容用 read_reference（ref 取上面 ref 串的 scenario 或 scenario/id 段）。"
        )
        if not packages:
            notes = (
                "未发现任何场景包——确认项目根下存在 <id>-package/agent_eval.yaml，"
                "或用 scenario new 创建。"
            ) + notes
        return {"packages": packages, "total": len(packages), "notes": notes}

    async def edit_package(self, ref: str = "") -> dict[str, Any]:
        """切换会话目标到既有包（原位编辑）——轻量修改的正道。

        执行序：①防卸与交互门槛（切根改变写域边界，必须有确认通道）→ ②定址
        （本地路径含清单 / ref 解析；builtin 只读拒绝）→ ③守卫（已在编辑 /
        staging 非空拒绝——rebind_root「调用时 staging 已清」的不变式）→ ④用户
        确认 → ⑤清旧根态（骨架归档/授权账本不跨根携带——归档骨架跨根携带会让
        旧包开槽卡住新包 validate）→ ⑥宿主切根（server 重绑 + 图重建 + 会话
        记录迁移 + 系统注记进对话）。落盘语义由既有路径保证：非草稿前缀根，
        确认后原位生效不归位。
        """
        _CONFIRM = "确认切换"
        if self.ask_fn is None:
            return {
                "status": "refused",
                "reason": "非交互环境不支持会话内切换编辑目标——请用 agent-eval scenario edit <ref>",
            }
        if self.relocate_fn is None:
            return {"error": "宿主未装配切根能力（relocate_fn 缺失）"}
        from agent_eval.packages import MANIFEST_FILENAME, PackageManager

        target_root: Path | None = None
        candidate = Path(ref).expanduser()
        if ref and (candidate / MANIFEST_FILENAME).is_file():
            target_root = candidate.resolve()
        else:
            try:
                pkg = PackageManager().resolve_ref(ref)
            except Exception as e:  # noqa: BLE001 — 解析失败转结构化错误（带指路）
                return {
                    "status": "not_found",
                    "reason": f"无法解析场景包 {ref!r}: {e}",
                    "next_step": "用 list_packages 查看可用包（ref 取 scenario 或 scenario/id 段）",
                }
            if pkg.source == "builtin":
                return {
                    "status": "refused",
                    "reason": f"内置包只读: {pkg.manifest.ref}——改造走 fork（scenario new，换新 id）",
                }
            target_root = Path(pkg.root).resolve()
        assert target_root is not None
        if target_root == self.root:
            return {"status": "already", "root": str(self.root), "note": "当前会话已在该包上编辑"}
        if self.staging:
            return {
                "status": "refused",
                "reason": "暂存区非空——跨根切换会造成脏暂存；先请用户「放弃」回滚或提交当前草稿，再切换",
            }
        old_root = self.root
        answer = await self.ask_fn(
            f"切换到原位编辑：\n  当前: {old_root}\n  目标: {target_root}\n"
            "切换后读写与确认落盘直接作用于该包（当前草稿不再随会话推进）。确认切换？",
            options=[_CONFIRM, "取消"],
            secret=False,
        )
        if answer != _CONFIRM:
            return {"status": "declined", "note": "未切换——仍在当前会话目标上"}
        # 旧根态不跨根携带：骨架归档（跨根携带会让旧包开槽卡住新包 validate）、
        # 外部路径授权账本（授权针对旧根路径，对新根无意义且越权）
        self.skeleton_archive = None
        self._granted.clear()
        self._denied.clear()
        self.relocate_fn(
            target_root,
            note=(
                f"（会话目标已切换：沙盒根从 {old_root} 迁移到 {target_root}——这是既有包的"
                "原位编辑，非归位。此后的文件读写、校验、确认落盘以新位置为准）"
            ),
        )
        return {
            "status": "switched",
            "root": str(target_root),
            "note": "已切换到原位编辑——read_file 定位后小步修改，validate_package + "
            "preview_diff 后请用户确认，落盘原位生效；轻量修改无需 SKELETON/五阶段/fork",
        }

    async def search_reference(self, query: str) -> dict[str, Any]:
        """检索内置包（只读）匹配文件 + 方法论要点。"""
        from agent_eval.packages import PackageManager

        hits = []
        for pkg in PackageManager().list(source="builtin"):
            for p in sorted(pkg.root.rglob("*.yaml")):
                if query.lower() in p.relative_to(pkg.root).as_posix().lower():
                    hits.append(f"{pkg.manifest.ref}::{p.relative_to(pkg.root).as_posix()}")
        return {"query": query, "matched_files": hits[:20], "notes": _reference_notes()}

    async def read_reference(
        self, ref: str, path: str, max_chars: int = _DEFAULT_REFERENCE_CHARS
    ) -> dict[str, Any]:
        """只读已发现包（三源）的文件内容（Agent 参照真实格式的合法通道，免沙盒逃逸）。

        ref 走 PackageManager 解析（如 ``chat`` / 项目包 ``courseware/courseware-reasonableness``，
        可用 ref 见 list_packages）；path 限目标包根内。
        """
        from agent_eval.packages import PackageManager

        try:
            pkg = PackageManager().resolve_ref(ref)
        except Exception as e:  # noqa: BLE001 — 错误交 Agent 自修复
            return {"error": f"参考包不存在: {ref}（{e}；先 list_packages 查可用包）"}
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

    async def list_evaluators(self) -> dict[str, Any]:
        """当前真实可用的评估器注册 ID 清单（rules 的 evaluator 从此原样复制）。

        快照与运行时/落盘门禁**同一真相源**（rule_refs 的装载原语：内置注册 +
        包 entry_points）；暂存清单已声明 entry_points 时一并装载——草稿期声明的
        chat.* 等场景评估器同样可见，避免「清单已声明却被告知不可用」的假阴性
        （教训：校验/工具的真相源必须与运行时同源）。
        """
        from agent_eval.evaluation.evaluators.plugins import load_package_entry_points
        from agent_eval.evaluation.registry import registry
        from agent_eval.evaluation.rule_refs import _registered_evaluator_ids

        _registered_evaluator_ids(self.root)  # 内置 + 磁盘清单 entry_points（幂等）
        if staged := self.staging.get(MANIFEST_FILENAME):
            with tempfile.TemporaryDirectory() as tmp:
                (Path(tmp) / MANIFEST_FILENAME).write_text(staged, encoding="utf-8")
                load_package_entry_points(tmp)  # 草稿未落盘的 entry_points 同样装入
        evaluators = sorted(registry.list_registered())
        # 判官模板变量契约（copy, don't recall 的变量面）：评估器类级 prompt_variables
        # 声明的实时快照——user_prompt_template 的变量从此原样复制，与落盘门禁同源
        # （契约表文档是副本，真相源在这里与评估器类声明）
        contracts = {
            eid: sorted(contract)
            for eid in evaluators
            if (cls := registry.class_of(eid)) is not None
            and (contract := getattr(cls, "prompt_variables", None)) is not None
        }
        note = (
            "rules 的 evaluator 字段必须从此清单**原样复制**——它是评估器注册 ID，"
            "不是 method 枚举值（llm_judge/llm 不是 ID）；清单含本包 entry_points "
            "声明的场景评估器（如 chat.*）"
        )
        if contracts:
            note += (
                "；prompt_variables 是各评估器判官模板（user_prompt_template）可用的"
                "变量清单，同样**原样复制**勿臆造（写错运行时报「模板渲染失败，变量缺失」）"
            )
        return {"evaluators": evaluators, "prompt_variables": contracts, "note": note}

    async def preview_diff(self) -> dict[str, Any]:
        """暂存 vs 磁盘的统一 diff（与宿主确认界面同源）。"""
        if not self.staging:
            return {
                "diff": "",
                "changed": 0,
                "note": "暂存区为空：先用 write_file/delete_file 产生变更再预览",
            }
        return {"diff": self.render_diff(), "changed": len(self.staging)}
