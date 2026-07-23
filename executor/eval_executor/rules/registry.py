"""executor 规则集资产（仅保留纯格式冒烟资产）。

S2-C/D 后 executor 不再内置 courseware 规则集映射（``_BUILTIN`` 已删除）：
业务规则集由 job.package_ref 经 ``agent_eval.packages.PackageManager`` 解析
（内置包 + 本地缓存 + 远端拉取，见 runner._resolve_rule_set_path）。
本模块仅保留无 LLM 依赖的 ``format_only.yaml``，供 CI 冒烟以**直接路径**调用评估。
"""

from __future__ import annotations

from pathlib import Path

# executor 自带规则集目录（纯格式冒烟用）
_EXECUTOR_ASSETS = Path(__file__).resolve().parent.parent / "assets" / "rules"


def format_only_path() -> Path:
    """纯格式规则集路径（CI 冒烟用，无 LLM 依赖）。"""
    return _EXECUTOR_ASSETS / "format_only.yaml"
