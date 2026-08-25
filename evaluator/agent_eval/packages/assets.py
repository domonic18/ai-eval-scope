"""包内资产解析 — 任务集与 SUT 接入配置（arch/16 §2.1）。

「怎么评 + 问什么 + 问谁」内聚于场景包：task_sets/（考卷）与 sut_configs/
（被测系统接入，不含凭证）从包内解析；显式路径参数可覆盖（--include_path 惯例）。
"""

from __future__ import annotations

from pathlib import Path

from agent_eval.core.exceptions import ScenarioPackageValidationError
from agent_eval.packages.manifest import ResolvedPackage

_YAML_EXTS = (".yaml", ".yml")


def resolve_task_set_path(pkg: ResolvedPackage, name: str | None = None) -> Path:
    """解析包内任务集文件。

    Args:
        pkg: 已解析的场景包。
        name: 任务集名（task_sets/ 下文件 stem）；缺省取 manifest 的
            ``default_task_set``，再缺省取目录内唯一文件。

    Raises:
        ScenarioPackageValidationError: 目录缺失 / 名称未找到 / 多文件无缺省。
    """
    directory = pkg.task_sets_dir
    if not directory.is_dir():
        raise ScenarioPackageValidationError(
            f"包 {pkg.manifest.ref} 无 task_sets/ 目录（考卷应内嵌于场景包，arch/16 §2.1）",
            details={"package": pkg.manifest.ref, "dir": str(directory)},
        )

    def _pick(stem: str) -> Path | None:
        for ext in _YAML_EXTS:
            candidate = directory / f"{stem}{ext}"
            if candidate.is_file():
                return candidate
        return None

    if name:
        hit = _pick(name)
        if hit is None:
            available = sorted(p.stem for p in directory.glob("*.y*ml"))
            raise ScenarioPackageValidationError(
                f"包 {pkg.manifest.ref} 未找到任务集 {name!r}；可用: {available}",
                details={"package": pkg.manifest.ref, "task_set": name, "available": available},
            )
        return hit

    default_name = pkg.manifest.default_task_set
    if default_name:
        hit = _pick(default_name)
        if hit is not None:
            return hit

    files = sorted(p for p in directory.iterdir() if p.suffix in _YAML_EXTS)
    if len(files) == 1:
        return files[0]
    names = [p.stem for p in files]
    raise ScenarioPackageValidationError(
        f"包 {pkg.manifest.ref} 的 task_sets/ 含多个任务集且未指定："
        f"用 --task-set 选择或 manifest 声明 default_task_set；可用: {names}",
        details={"package": pkg.manifest.ref, "available": names},
    )


def resolve_sut_configs_dir(pkg: ResolvedPackage) -> Path:
    """解析包内 SUT 注册表目录（sut_configs/；多系统经 SUTRegistry 聚合）。

    Raises:
        ScenarioPackageValidationError: 目录缺失或不含 yaml（run 型场景必需）。
    """
    directory = pkg.sut_configs_dir
    if not directory.is_dir() or not any(p.suffix in _YAML_EXTS for p in directory.iterdir()):
        raise ScenarioPackageValidationError(
            f"包 {pkg.manifest.ref} 无 sut_configs/（被测系统接入应内嵌于场景包，"
            "arch/16 §2.1；eval_only 型场景无此目录）",
            details={"package": pkg.manifest.ref, "dir": str(directory)},
        )
    return directory


__all__ = ["resolve_sut_configs_dir", "resolve_task_set_path"]
