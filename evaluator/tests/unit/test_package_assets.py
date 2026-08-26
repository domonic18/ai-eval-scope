"""包内资产解析测试 — task_sets/ 与 sut_configs/（arch/16 §2.1，W1）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_eval.core.exceptions import ScenarioPackageValidationError
from agent_eval.packages.assets import resolve_sut_configs_dir, resolve_task_set_path
from agent_eval.packages.manifest import PackageManifest, ResolvedPackage


def _pkg(tmp_path: Path, *, default_task_set: str | None = None) -> ResolvedPackage:
    return ResolvedPackage(
        manifest=PackageManifest(
            id="chat", scenario="chat", version="1.0.0", default_task_set=default_task_set
        ),
        root=tmp_path,
    )


def _write(path: Path, name: str, content: str = "id: t\nname: t\ntasks: []\n") -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / name).write_text(content, encoding="utf-8")


class TestResolveTaskSet:
    def test_explicit_name(self, tmp_path: Path) -> None:
        _write(tmp_path / "task_sets", "default.yaml")
        _write(tmp_path / "task_sets", "regression.yaml")
        hit = resolve_task_set_path(_pkg(tmp_path), "regression")
        assert hit.name == "regression.yaml"

    def test_manifest_default(self, tmp_path: Path) -> None:
        _write(tmp_path / "task_sets", "default.yaml")
        _write(tmp_path / "task_sets", "regression.yaml")
        hit = resolve_task_set_path(_pkg(tmp_path, default_task_set="regression"))
        assert hit.name == "regression.yaml"

    def test_single_file_without_default(self, tmp_path: Path) -> None:
        _write(tmp_path / "task_sets", "default.yaml")
        assert resolve_task_set_path(_pkg(tmp_path)).name == "default.yaml"

    def test_multiple_without_default_raises_with_options(self, tmp_path: Path) -> None:
        _write(tmp_path / "task_sets", "a.yaml")
        _write(tmp_path / "task_sets", "b.yaml")
        with pytest.raises(ScenarioPackageValidationError, match="default_task_set"):
            resolve_task_set_path(_pkg(tmp_path))

    def test_unknown_name_lists_available(self, tmp_path: Path) -> None:
        _write(tmp_path / "task_sets", "a.yaml")
        with pytest.raises(ScenarioPackageValidationError, match="可用"):
            resolve_task_set_path(_pkg(tmp_path), "nope")

    def test_missing_dir_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ScenarioPackageValidationError, match="task_sets"):
            resolve_task_set_path(_pkg(tmp_path))


class TestResolveSutConfigs:
    def test_dir_with_yaml(self, tmp_path: Path) -> None:
        _write(tmp_path / "sut_configs", "sasan-agent.yaml", "sut:\n  name: s\n  base_url: u\n")
        assert resolve_sut_configs_dir(_pkg(tmp_path)).name == "sut_configs"

    def test_missing_dir_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ScenarioPackageValidationError, match="sut_configs"):
            resolve_sut_configs_dir(_pkg(tmp_path))
