"""LLM 配置文件（`~/.agent_eval/llm.json`）— CLI 形态的本地存储（arch/16 §6.2-四）。

`agent-eval models login` 交互式写入；**0600 权限**（对标 gh / AWS CLI / opencode
的密钥文件惯例）：不打印、不入日志、家目录天然不入 git。路径可经
``AGENT_EVAL_LLM_CONFIG`` 覆盖（多环境隔离）。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from pydantic import BaseModel, Field

from agent_eval.core.exceptions import ConfigError

FILE_VERSION = 1

#: 固定三角色（providers 键）
ROLES = ("text", "vision", "agent")
DEFAULT_ROLE = "text"

#: 各提供商建议端点（login 向导默认值；团队统一走 Moonshot anthropic 兼容端点）
PROVIDER_DEFAULT_BASE_URLS = {
    "anthropic": "https://api.moonshot.cn/anthropic",
    "openai": "https://api.openai.com/v1",
    "deepseek": "https://api.deepseek.com/v1",
}
#: login 向导的模型建议值（agent 无建议=可跳过回退 text）
ROLE_MODEL_SUGGESTIONS = {"text": "moonshot-v1-128k", "vision": "kimi-k2.6", "agent": ""}


class RoleConfig(BaseModel):
    """单个角色的模型配置（api_key 与偏好同文件，整文件 0600 保护）。"""

    provider: str
    model: str
    api_key: str = Field(repr=False)
    base_url: str | None = None
    max_tokens: int | None = None
    temperature: float | None = None
    seed: int | None = None


class LLMFileConfig(BaseModel):
    """llm.json 结构。roles 值为 null 表示该角色未配置（agent 缺省回退 text）。"""

    version: int = FILE_VERSION
    default_role: str = DEFAULT_ROLE
    roles: dict[str, RoleConfig | None] = Field(default_factory=dict)


def llm_file_path() -> Path:
    """配置文件路径：``AGENT_EVAL_LLM_CONFIG`` 覆盖 > ``~/.agent_eval/llm.json``。"""
    override = os.environ.get("AGENT_EVAL_LLM_CONFIG", "").strip()
    if override:
        return Path(override).expanduser()
    return Path.home() / ".agent_eval" / "llm.json"


def load_llm_file(path: Path | None = None) -> LLMFileConfig | None:
    """加载配置文件；文件不存在返回 None（未配置）。

    Raises:
        ConfigError: 文件损坏（非法 JSON / 结构不符 / 未知角色键）。
    """
    p = path or llm_file_path()
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        raise ConfigError(f"LLM 配置文件损坏: {p}（{e}）", details={"path": str(p)}) from e
    cfg = LLMFileConfig.model_validate(data)
    unknown = set(cfg.roles) - set(ROLES)
    if unknown:
        raise ConfigError(
            f"LLM 配置含未知角色: {sorted(unknown)}（可选 {list(ROLES)}）",
            details={"path": str(p)},
        )
    return cfg


def save_llm_file(cfg: LLMFileConfig, path: Path | None = None) -> Path:
    """写入配置文件并收紧权限至 0600（父目录按需创建）。"""
    p = path or llm_file_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(cfg.model_dump(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.chmod(p, 0o600)
    return p


__all__ = [
    "DEFAULT_ROLE",
    "PROVIDER_DEFAULT_BASE_URLS",
    "ROLES",
    "ROLE_MODEL_SUGGESTIONS",
    "LLMFileConfig",
    "RoleConfig",
    "llm_file_path",
    "load_llm_file",
    "save_llm_file",
]
