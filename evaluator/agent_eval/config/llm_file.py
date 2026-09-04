"""LLM 配置文件（`~/.agent_eval/llm.json`）— CLI 形态的本地存储（arch/06 §4.6）。

`agent-eval models set` 交互式写入；**0600 权限**（对标 gh / AWS CLI / opencode
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

#: 线路协议（分发键）——预置厂商均双协议提供，向导第二层选择
PROTOCOLS = ("anthropic", "openai")

#: 预置厂商（展示名与存储键分离；custom 之外免输 base_url）
PROVIDER_LABELS = {
    "deepseek": "DeepSeek",
    "kimi": "Kimi",
    "zhipu": "智谱",
    "minimax": "MiniMax",
}
PROVIDERS = tuple(PROVIDER_LABELS)

#: (厂商, 协议) → 预置端点（官方公开端点；向导直接采用并向用户展示）
PROVIDER_DEFAULT_BASE_URLS: dict[tuple[str, str], str] = {
    ("deepseek", "openai"): "https://api.deepseek.com/v1",
    ("deepseek", "anthropic"): "https://api.deepseek.com/anthropic",
    ("kimi", "openai"): "https://api.moonshot.cn/v1",
    ("kimi", "anthropic"): "https://api.moonshot.cn/anthropic",
    ("zhipu", "openai"): "https://open.bigmodel.cn/api/paas/v4",
    ("zhipu", "anthropic"): "https://open.bigmodel.cn/api/anthropic",
    ("minimax", "openai"): "https://api.minimaxi.com/v1",
    ("minimax", "anthropic"): "https://api.minimaxi.com/anthropic",
}

#: 厂商 × 角色的模型建议值（向导默认值；留空 = 无建议，用户自输）。
#: agent 角色不进向导（执行引擎/工作台 Agent 专用，未配置自动回退 text）。
#: 建议值随厂商旗舰更新（2026-08 核对：deepseek-v4-pro / kimi-k3 / glm-5.3 / MiniMax-M3；
#: moonshot-v1 系列已下线，勿再作为建议值）
PROVIDER_MODEL_SUGGESTIONS: dict[str, dict[str, str]] = {
    "deepseek": {"text": "deepseek-v4-pro", "vision": ""},
    "kimi": {"text": "kimi-k3", "vision": "kimi-k2.6"},
    "zhipu": {"text": "glm-5.3", "vision": "glm-5.3-flash"},
    "minimax": {"text": "MiniMax-M3", "vision": "MiniMax-M3"},
    "custom": {"text": "", "vision": ""},
}


def effective_protocol(provider: str, protocol: str | None) -> str:
    """角色配置的线路协议归一（分发键）：新配置读显式 ``protocol``；旧文件（v1，
    无 protocol 字段）按 provider 值推断——``anthropic`` 之外均按 OpenAI 兼容。"""
    if protocol in PROTOCOLS:
        return protocol
    return "anthropic" if provider == "anthropic" else "openai"


class RoleConfig(BaseModel):
    """单个角色的模型配置（api_key 与偏好同文件，整文件 0600 保护）。"""

    provider: str = Field(description="厂商: deepseek | kimi | zhipu | minimax | custom")
    protocol: str | None = Field(
        default=None, description="线路协议: anthropic | openai（缺省=旧版文件，按 provider 推断）"
    )
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
    "PROTOCOLS",
    "PROVIDERS",
    "PROVIDER_DEFAULT_BASE_URLS",
    "PROVIDER_LABELS",
    "PROVIDER_MODEL_SUGGESTIONS",
    "ROLES",
    "LLMFileConfig",
    "RoleConfig",
    "effective_protocol",
    "llm_file_path",
    "load_llm_file",
    "save_llm_file",
]
