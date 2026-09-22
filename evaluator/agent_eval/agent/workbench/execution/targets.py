"""TargetsTool — 可评测对象枚举（list_eval_targets）。

与 CLI ``scenario list`` / workbench ``list_packages`` 同真相源
（PackageManager 三源发现）；在包清单之上补 task_sets/suts/rule_sets 概要——
run_evaluation 选参（task_set/sut_name/rule_set）的全部合法值由此而来。
"""

from __future__ import annotations

from typing import Any


def _stems(directory: Any) -> list[str]:
    """目录下 *.yaml 文件 stem（目录缺省/读取异常 → 空清单，不阻断枚举）。"""
    if directory is None:
        return []
    try:
        return sorted(p.stem for p in directory.glob("*.yaml"))
    except OSError:
        return []


class TargetsTool:
    """工具：list_eval_targets——只读枚举，无授权需求。"""

    def __init__(self, ctx: Any) -> None:
        self.ctx = ctx

    async def list_eval_targets(self, source: str = "") -> dict[str, Any]:
        from agent_eval.packages import PackageManager

        if source and source not in ("builtin", "local", "project"):
            return {"error": f"未知 source: {source}（可选 builtin / local / project，缺省全部）"}

        packages = []
        for pkg in PackageManager().list(source=source or None):
            manifest = pkg.manifest
            task_sets = _stems(getattr(pkg, "task_sets_dir", None))
            suts = _stems(getattr(pkg, "sut_configs_dir", None))
            rule_sets = _stems(getattr(pkg, "rules_dir", None))
            packages.append(
                {
                    "ref": manifest.ref,
                    "source": pkg.source,
                    "path": str(pkg.root),
                    "name": manifest.name,
                    "version": manifest.version,
                    "description": manifest.description,
                    "editable": pkg.source != "builtin",
                    "default_task_set": getattr(manifest, "default_task_set", None),
                    "task_sets": task_sets,
                    "suts": suts,
                    "rule_sets": rule_sets,
                    # 唯一值不须显式传参（resolve 链自动选中）——选参提示用
                    "notes": (
                        f"task_set 缺省取 {task_sets[0] if len(task_sets) == 1 else '须从清单选一'}；"
                        f"sut_name 缺省取 {suts[0] if len(suts) == 1 else '须从清单选一'}"
                        if (task_sets or suts)
                        else "包内无任务集/SUT 清单，run_evaluation 需显式路径"
                    ),
                }
            )
        self.ctx.log("list_eval_targets", source=source or "all", total=len(packages))
        if not packages:
            return {
                "packages": [],
                "total": 0,
                "note": (
                    "未发现任何场景包——确认项目根下存在 <id>-package/agent_eval.yaml，"
                    "或先用场景包管理创建/探测（sut_probe 域）"
                ),
            }
        return {
            "packages": packages,
            "total": len(packages),
            "note": "run_evaluation 的 package 填 ref（如 chat 或 chat:1.0.0）；改包走场景包管理",
        }
