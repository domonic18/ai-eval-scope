"""平台身份文件（`~/.agent_eval/platform.json`）— auth 域本地存储（arch/06 §4.7）。

`agent-eval auth login` 交互写入 host/api_key/project；**0600 密钥区**，与
llm.json / sut_credentials.json 同目录同权限惯例（三域三文件：models/secrets/auth）。
路径可经 ``AGENT_EVAL_PLATFORM_CONFIG`` 覆盖（多环境隔离）。

消费面是只读 ``os.environ`` 的 ``ObservabilityConfig`` / ``LLMPlatform``——经
:func:`apply_platform_env` 在 CLI 启动时注入进程 env，**env 已设则跳过**
（CI / 云函数 / docker executor 直供优先，本地密钥区只是缺省补位）。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from pydantic import BaseModel, Field

FILE_VERSION = 1

_ENV_KEYS = ("AGENT_EVAL_HOST", "AGENT_EVAL_API_KEY", "AGENT_EVAL_PROJECT")


class PlatformFileConfig(BaseModel):
    """platform.json 结构（api_key 不回显）。"""

    version: int = FILE_VERSION
    host: str
    api_key: str = Field(repr=False)
    project: str | None = None


def platform_file_path() -> Path:
    """配置文件路径：``AGENT_EVAL_PLATFORM_CONFIG`` 覆盖 > ``~/.agent_eval/platform.json``。"""
    override = os.environ.get("AGENT_EVAL_PLATFORM_CONFIG", "").strip()
    if override:
        return Path(override).expanduser()
    return Path.home() / ".agent_eval" / "platform.json"


def load_platform_file(path: Path | None = None) -> PlatformFileConfig | None:
    """加载平台身份文件；不存在返回 None（未登录）。

    Raises:
        ConfigError: 文件损坏（非法 JSON / 结构不符）。
    """
    from agent_eval.core.exceptions import ConfigError

    p = path or platform_file_path()
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return PlatformFileConfig.model_validate(data)
    except (json.JSONDecodeError, OSError, ValueError) as e:
        raise ConfigError(f"平台身份文件损坏: {p}（{e}）", details={"path": str(p)}) from e


def save_platform_file(cfg: PlatformFileConfig, path: Path | None = None) -> Path:
    """写入平台身份文件并收紧权限至 0600（父目录按需创建）。"""
    p = path or platform_file_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(cfg.model_dump(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.chmod(p, 0o600)
    return p


def apply_platform_env(path: Path | None = None, *, env: dict[str, str] | None = None) -> bool:
    """把 platform.json 注入进程 env（仅补缺，**env 已设则不覆盖**）。

    CLI 启动时调用（main.py，load_dotenv 之后）：.env / shell / CI 显式 env
    优先，密钥区文件只是缺省补位。返回是否注入了任何键。
    """
    cfg = load_platform_file(path)
    if cfg is None:
        return False
    target = os.environ if env is None else env
    values = {
        "AGENT_EVAL_HOST": cfg.host.rstrip("/"),
        "AGENT_EVAL_API_KEY": cfg.api_key,
        **({"AGENT_EVAL_PROJECT": cfg.project} if cfg.project else {}),
    }
    injected = False
    for key, value in values.items():
        if not target.get(key, "").strip():
            target[key] = value
            injected = True
    return injected


__all__ = [
    "PlatformFileConfig",
    "apply_platform_env",
    "load_platform_file",
    "platform_file_path",
    "save_platform_file",
]
