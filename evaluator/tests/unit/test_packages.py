"""Phase 2 场景包（Scenario Package）测试 — manifest / store / manager / CLI。

对齐 13 配置管理设计 §四/§五。本地缓存用 ``AGENT_EVAL_PACKAGE_DIR`` + ``tmp_path`` 隔离，
pull 远端用 FakeRemotePackageClient 注入，禁止联网。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

import agent_eval.config  # noqa: F401  触发正常初始化顺序，规避潜在 circular import
from agent_eval.cli.cmds.scenario import scenario_app
from agent_eval.core.exceptions import ScenarioPackageNotFoundError, ScenarioPackageValidationError
from agent_eval.packages import (
    FakeRemotePackageClient,
    PackageManager,
    PackageManifest,
    PackageStore,
    RemotePackage,
    load_manifest,
    parse_ref,
)

# ── manifest / parse_ref ────────────────────────────────────────────────────────


def test_parse_ref_variants() -> None:
    assert parse_ref("courseware") == ("courseware", None, None)
    assert parse_ref("courseware/quality") == ("courseware", "quality", None)
    assert parse_ref("courseware/quality:production") == ("courseware", "quality", "production")
    assert parse_ref("courseware:1.0.0") == ("courseware", None, "1.0.0")


def test_load_manifest_missing(tmp_path: Path) -> None:
    with pytest.raises(ScenarioPackageValidationError):
        load_manifest(tmp_path)


def test_load_manifest_no_package_section(tmp_path: Path) -> None:
    (tmp_path / "agent_eval.yaml").write_text("foo: bar\n", encoding="utf-8")
    with pytest.raises(ScenarioPackageValidationError):
        load_manifest(tmp_path)


# ── PackageStore / PackageManager ───────────────────────────────────────────────


def test_builtin_courseware_listed_and_resolvable() -> None:
    mgr = PackageManager()
    pkgs = mgr.list(source="builtin")
    assert any(p.manifest.id == "courseware" for p in pkgs)
    pkg = mgr.resolve("courseware")
    assert pkg.manifest.id == "courseware"
    assert pkg.manifest.version == "1.0.0"
    assert pkg.rules_dir.exists() and pkg.prompts_dir.exists()


def test_resolve_by_label_and_version() -> None:
    mgr = PackageManager()
    assert mgr.resolve("courseware", version_or_label="latest").manifest.version == "1.0.0"
    assert mgr.resolve("courseware", version_or_label="production").manifest.version == "1.0.0"
    assert mgr.resolve("courseware", version_or_label="1.0.0").manifest.version == "1.0.0"


def test_resolve_unknown_raises() -> None:
    with pytest.raises(ScenarioPackageNotFoundError):
        PackageManager().resolve("no-such-scenario")


def test_resolve_picks_highest_version(tmp_path: Path) -> None:
    store = PackageStore(local_root=tmp_path / "local")
    # 造两个版本的本地包
    for ver in ("1.0.0", "1.2.0"):
        root = tmp_path / "local" / "demo" / "demo" / ver
        (root / "rules").mkdir(parents=True)
        (root / "agent_eval.yaml").write_text(
            f"package:\n  id: demo\n  scenario: demo\n  version: {ver}\n", encoding="utf-8"
        )
    mgr = PackageManager(store=store)
    assert mgr.resolve("demo").manifest.version == "1.2.0"
    assert mgr.resolve("demo", version_or_label="1.0.0").manifest.version == "1.0.0"


def test_store_install_then_list_local(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_EVAL_PACKAGE_DIR", str(tmp_path / "cache"))
    store = PackageStore()
    manifest = PackageManifest(id="t", scenario="t", version="1.0.0", name="T")
    root = store.install(manifest, {"rules/r1.yaml": "version: '1.0'\n"})
    assert (root / "agent_eval.yaml").exists()
    assert (root / "rules" / "r1.yaml").exists()
    local = PackageStore().list_local()
    assert any(p.manifest.id == "t" for p in local)


# ── CLI ─────────────────────────────────────────────────────────────────────────


runner = CliRunner()


def test_cli_init_creates_scaffold(tmp_path: Path) -> None:
    result = runner.invoke(
        scenario_app,
        [
            "new",
            "travel-itinerary/quality",
            "--mode",
            "skeleton",
            "--output",
            str(tmp_path / "pkg"),
        ],
    )
    assert result.exit_code == 0, result.output
    root = tmp_path / "pkg"
    assert (root / "agent_eval.yaml").exists()
    for sub in ("rules", "prompts", "datasets"):
        assert (root / sub).is_dir()
    manifest = load_manifest(root)
    assert manifest.id == "quality" and manifest.scenario == "travel-itinerary"


def test_cli_validate(tmp_path: Path) -> None:
    # 复用 init 产出的包做 validate
    runner.invoke(
        scenario_app, ["new", "demo/pkg", "--mode", "skeleton", "--output", str(tmp_path / "p")]
    )
    result = runner.invoke(scenario_app, ["validate", str(tmp_path / "p")])
    assert result.exit_code == 0, result.output
    assert "校验通过" in result.output


def test_cli_validate_missing_dir(tmp_path: Path) -> None:
    (tmp_path / "agent_eval.yaml").write_text(
        "package:\n  id: x\n  scenario: x\n  version: 1.0.0\n", encoding="utf-8"
    )
    result = runner.invoke(scenario_app, ["validate", str(tmp_path)])
    assert result.exit_code == 1
    assert "缺少资源目录" in result.output


def test_cli_list_builtin() -> None:
    result = runner.invoke(scenario_app, ["list", "--source", "builtin"])
    assert result.exit_code == 0, result.output
    assert "courseware" in result.output


def test_cli_pull_with_fake_remote(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_EVAL_PACKAGE_DIR", str(tmp_path / "cache"))
    # 注入假远端客户端
    import agent_eval.packages as pkgmod

    manifest = PackageManifest(id="remote-pkg", scenario="remote", version="1.0.0")
    fake = FakeRemotePackageClient(
        {
            "remote/remote-pkg:1.0.0": RemotePackage(
                manifest=manifest, files={"rules/r.yaml": b"v: 1\n"}
            )
        }
    )
    monkeypatch.setattr(pkgmod, "get_remote_client", lambda: fake)

    result = runner.invoke(scenario_app, ["pull", "remote/remote-pkg:1.0.0"])
    assert result.exit_code == 0, result.output
    assert "已拉取" in result.output
    installed = tmp_path / "cache" / "remote" / "remote-pkg" / "1.0.0"
    assert (installed / "agent_eval.yaml").exists()
    assert (installed / "rules" / "r.yaml").exists()


def test_cli_pull_no_remote_configured() -> None:
    # 默认 get_remote_client 返回 None → 友好提示 + exit 1
    result = runner.invoke(scenario_app, ["pull", "anything/x:1.0.0"])
    assert result.exit_code == 1
    assert "未配置" in result.output
