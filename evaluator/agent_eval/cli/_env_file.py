"""`.env` 文件更新助手（arch/15 D-CLI-4：平台身份落 .env，0600）。

auth login/logout 专用：保序保注释的键值更新与删除；不引入 python-dotenv 的
写回能力（其不保留注释顺序），按行解析足够 KISS。
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

_ENV_KEYS = ("AGENT_EVAL_HOST", "AGENT_EVAL_API_KEY", "AGENT_EVAL_PROJECT")


def find_env_path() -> Path:
    """定位 `.env`：从 cwd 向上找已有文件 → git 根 → cwd（不存在则新建于此）。"""
    cwd = Path.cwd()
    for cur in (cwd, *cwd.parents):
        if (cur / ".env").is_file():
            return cur / ".env"
    for cur in (cwd, *cwd.parents):
        if (cur / ".git").exists():
            return cur / ".env"
    return cwd / ".env"


def upsert_env(path: Path, updates: dict[str, str]) -> None:
    """按键更新/追加 `.env`（保序保注释），文件权限收紧 0600（D-CLI-4）。"""
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    seen: set[str] = set()
    out: list[str] = []
    for line in lines:
        key = (
            line.split("=", 1)[0].strip()
            if "=" in line and not line.lstrip().startswith("#")
            else ""
        )
        if key in updates:
            out.append(f"{key}={updates[key]}")
            seen.add(key)
        else:
            out.append(line)
    for key, value in updates.items():
        if key not in seen:
            out.append(f"{key}={value}")
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)  # 0600：含 API Key，仅属主可读写


def remove_env_keys(path: Path, keys: tuple[str, ...] = _ENV_KEYS) -> int:
    """从 `.env` 删除指定键（含其行），返回删除条数；文件不存在返回 0。"""
    if not path.is_file():
        return 0
    out: list[str] = []
    removed = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = (
            line.split("=", 1)[0].strip()
            if "=" in line and not line.lstrip().startswith("#")
            else ""
        )
        if stripped in keys:
            removed += 1
            continue
        out.append(line)
    if removed:
        path.write_text("\n".join(out) + "\n", encoding="utf-8")
    return removed
