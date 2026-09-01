"""platform_file 单测 — 密钥区读写与 env 注入优先级（arch/06 §4.7）。"""

from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

from agent_eval.config.platform_file import (
    PlatformFileConfig,
    apply_platform_env,
    load_platform_file,
    platform_file_path,
    save_platform_file,
)
from agent_eval.core.exceptions import ConfigError


def test_path_env_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AGENT_EVAL_PLATFORM_CONFIG", str(tmp_path / "p.json"))
    assert platform_file_path() == tmp_path / "p.json"


def test_roundtrip_0600(tmp_path: Path) -> None:
    path = save_platform_file(
        PlatformFileConfig(host="http://p/", api_key="eval-x", project="demo"),
        path=tmp_path / "p.json",
    )
    assert stat.S_IMODE(path.stat().st_mode) == stat.S_IRUSR | stat.S_IWUSR
    cfg = load_platform_file(path)
    assert cfg is not None
    assert cfg.host == "http://p/" and cfg.api_key == "eval-x" and cfg.project == "demo"
    # api_key 不出现在 repr（模型 dump 含值是落盘需要，repr 不回显）
    assert "eval-x" not in repr(cfg)


def test_load_missing_returns_none(tmp_path: Path) -> None:
    assert load_platform_file(tmp_path / "none.json") is None


def test_load_corrupt_raises_config_error(tmp_path: Path) -> None:
    p = tmp_path / "p.json"
    p.write_text("{broken", encoding="utf-8")
    with pytest.raises(ConfigError, match="损坏"):
        load_platform_file(p)


def test_apply_platform_env_fills_only_missing(tmp_path: Path) -> None:
    path = tmp_path / "p.json"
    save_platform_file(
        PlatformFileConfig(host="http://file", api_key="eval-file", project="proj"), path=path
    )
    env = {"AGENT_EVAL_HOST": "http://env-wins", "OTHER": "x"}
    assert apply_platform_env(path, env=env) is True
    assert env["AGENT_EVAL_HOST"] == "http://env-wins"  # env 已设不覆盖（env 优先）
    assert env["AGENT_EVAL_API_KEY"] == "eval-file"  # 缺失补位
    assert env["AGENT_EVAL_PROJECT"] == "proj"


def test_apply_platform_env_no_file_noop(tmp_path: Path) -> None:
    env: dict[str, str] = {}
    assert apply_platform_env(tmp_path / "none.json", env=env) is False
    assert env == {}


def test_apply_platform_env_without_project_skips_key(tmp_path: Path) -> None:
    path = tmp_path / "p.json"
    save_platform_file(PlatformFileConfig(host="http://p", api_key="eval-x"), path=path)
    env: dict[str, str] = {}
    apply_platform_env(path, env=env)
    assert "AGENT_EVAL_PROJECT" not in env  # project 未配置不注入空值


def test_saved_json_shape(tmp_path: Path) -> None:
    path = tmp_path / "p.json"
    save_platform_file(PlatformFileConfig(host="http://p", api_key="eval-x"), path=path)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["version"] == 1 and data["host"] == "http://p" and data["project"] is None
