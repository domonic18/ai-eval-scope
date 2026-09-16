"""`.env` 平台配置残留检测（只读）——auth 登录/登出的防错乱提示用。

平台身份的正存储是密钥区 ``~/.agent_eval/platform.json``（arch/06 §4.7）；
``.env`` 归用户手工管理（CI / 云函数 / docker executor 直供通道），auth
**不代为读写**——但 env 优先于密钥区，残留旧值会静默覆盖本次登录
（回执 B、实际上报 A），故登录/登出时检测到即提示，由用户自行删改。
"""

from __future__ import annotations

from pathlib import Path

_ENV_KEYS = ("AGENT_EVAL_HOST", "AGENT_EVAL_API_KEY", "AGENT_EVAL_PROJECT")


def find_env_path() -> Path:
    """定位 `.env`：从 cwd 向上找已有文件 → git 根 → cwd（不存在即新建于此的路径）。"""
    cwd = Path.cwd()
    for cur in (cwd, *cwd.parents):
        if (cur / ".env").is_file():
            return cur / ".env"
    for cur in (cwd, *cwd.parents):
        if (cur / ".git").exists():
            return cur / ".env"
    return cwd / ".env"


def platform_keys_in_env(path: Path, keys: tuple[str, ...] = _ENV_KEYS) -> list[str]:
    """`.env` 中存在（非注释、有赋值）的平台配置键名；文件不存在返回空。"""
    if not path.is_file():
        return []
    present: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or "=" not in stripped:
            continue
        key = stripped.split("=", 1)[0].strip()
        if key in keys and key not in present:
            present.append(key)
    return present
