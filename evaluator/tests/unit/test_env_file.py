"""_env_file 单测 — .env 保序保注释更新 / 删除 / 0600（arch/15 D-CLI-4）。"""

from __future__ import annotations

import stat
from pathlib import Path

import pytest

from agent_eval.cli._env_file import find_env_path, remove_env_keys, upsert_env


def test_upsert_appends_and_updates_preserving_comments(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("# 平台\nAGENT_EVAL_HOST=http://a\nOTHER=1\n", encoding="utf-8")
    upsert_env(
        env,
        {"AGENT_EVAL_HOST": "http://b", "AGENT_EVAL_API_KEY": "eval-x", "AGENT_EVAL_PROJECT": "p"},
    )
    lines = env.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "# 平台"  # 注释保序
    assert "AGENT_EVAL_HOST=http://b" in lines  # 原位更新
    assert "OTHER=1" in lines  # 无关键不动
    assert "AGENT_EVAL_API_KEY=eval-x" in lines  # 追加
    mode = stat.S_IMODE(env.stat().st_mode)
    assert mode == stat.S_IRUSR | stat.S_IWUSR  # 0600


def test_upsert_creates_missing_file(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    upsert_env(env, {"AGENT_EVAL_HOST": "http://a"})
    assert env.read_text(encoding="utf-8") == "AGENT_EVAL_HOST=http://a\n"


def test_remove_env_keys_drops_only_targets(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text(
        "AGENT_EVAL_HOST=http://a\nKEEP=1\nAGENT_EVAL_API_KEY=eval-x\n"
        "# AGENT_EVAL_PROJECT=注释行不应被删\n",
        encoding="utf-8",
    )
    removed = remove_env_keys(env)
    text = env.read_text(encoding="utf-8")
    assert removed == 2
    assert "KEEP=1" in text
    assert "AGENT_EVAL_HOST" not in text
    assert "# AGENT_EVAL_PROJECT=注释行不应被删" in text  # 注释行不是赋值行


def test_remove_missing_file_is_noop(tmp_path: Path) -> None:
    assert remove_env_keys(tmp_path / ".env") == 0


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
