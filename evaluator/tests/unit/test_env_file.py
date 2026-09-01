"""_env_file 单测 — .env 平台配置残留检测（只读，auth 防错乱提示用）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_eval.cli._env_file import find_env_path, platform_keys_in_env


def test_platform_keys_detects_active_assignments_only(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text(
        "# AGENT_EVAL_API_KEY=注释行不算\n"
        "AGENT_EVAL_HOST=http://a\n"
        "OTHER=1\n"
        "AGENT_EVAL_API_KEY=eval-x\n"
        "AGENT_EVAL_PROJECT = spaced\n",  # 键两侧空白容忍
        encoding="utf-8",
    )
    assert platform_keys_in_env(env) == [
        "AGENT_EVAL_HOST",
        "AGENT_EVAL_API_KEY",
        "AGENT_EVAL_PROJECT",
    ]


def test_platform_keys_missing_file_is_empty(tmp_path: Path) -> None:
    assert platform_keys_in_env(tmp_path / ".env") == []


def test_find_env_path_walks_up_then_git_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    (repo / "sub" / "dir").mkdir(parents=True)
    (repo / ".git").mkdir()
    monkeypatch.chdir(repo / "sub" / "dir")
    assert find_env_path() == repo / ".env"  # 无 .env → git 根
    assert not find_env_path().exists()  # 只定位，不创建

    (repo / "sub" / ".env").write_text("X=1\n", encoding="utf-8")
    assert find_env_path() == repo / "sub" / ".env"  # 向上最近的 .env

    monkeypatch.chdir(tmp_path)
    assert find_env_path() == tmp_path / ".env"  # 兜底 cwd
