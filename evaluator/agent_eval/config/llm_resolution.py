"""LLM 角色注册表解析 — 双形态统一入口（arch/06 §4.6，v1.3）。

优先级（两形态互不感知，仅共享本解析接口）：

  1. 本地 `~/.agent_eval/llm.json`（CLI 形态，`agent-eval models set` 写入）
  2. 平台拉取（云端形态）：`AGENT_EVAL_HOST`/`AGENT_EVAL_API_KEY` 已配置时调
     `GET /api/public/llm-config`，返回 `{roles: {text: {...含解密 api_key}, ...}}`
  3. 均不可用 → ConfigError（报缺什么、在哪补）

产出 `LLMConfig`：providers 键 = 角色名（text/vision/agent），default=text——
ProviderPool / 客户端工厂 / LangChain 桥接对角色名零改动。agent 角色缺省回退 text。
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import httpx

from agent_eval.config.llm import LLMConfig, ProviderConfig
from agent_eval.config.llm_file import (
    DEFAULT_ROLE,
    ROLES,
    LLMFileConfig,
    effective_protocol,
    load_llm_file,
)
from agent_eval.core.exceptions import ConfigError


class LLMPlatform:
    """平台 LLM 配置拉取客户端（云端形态；`_get_json` 可覆写供测试隔离网络）。"""

    def __init__(self, host: str, api_key: str) -> None:
        self._host = host.rstrip("/")
        self._api_key = api_key

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> LLMPlatform | None:
        """host 与 API Key 均已配置才启用（与上报/凭证通道复用同一对变量）。"""
        source: Mapping[str, str] = os.environ if env is None else env
        host = source.get("AGENT_EVAL_HOST", "").strip()
        api_key = source.get("AGENT_EVAL_API_KEY", "").strip()
        return cls(host, api_key) if host and api_key else None

    def fetch(self) -> dict[str, dict[str, Any]] | None:
        """拉取角色配置；平台未配置任何角色返回 None。"""
        data = self._get_json(f"{self._host}/api/public/llm-config")
        roles = data.get("roles") if isinstance(data, dict) else None
        if not isinstance(roles, dict):
            return None
        out: dict[str, dict[str, Any]] = {}
        for role, cfg in roles.items():
            if role in ROLES and isinstance(cfg, dict) and cfg:
                out[role] = {k: v for k, v in cfg.items() if isinstance(v, (str, int, float))}
        return out or None

    def _get_json(self, url: str) -> object | None:
        response = httpx.get(
            url, headers={"Authorization": f"Bearer {self._api_key}"}, timeout=10.0
        )
        if response.status_code == 404:
            return None
        if response.status_code != 200:
            raise ConfigError(
                f"平台 LLM 配置拉取失败: HTTP {response.status_code}",
                details={"status_code": response.status_code},
            )
        result: object = response.json()
        return result


def _build_provider(
    provider: str,
    model: str,
    api_key: str,
    base_url: Any = None,
    max_tokens: Any = None,
    temperature: Any = None,
    seed: Any = None,
) -> ProviderConfig:
    """构造 ProviderConfig（None 字段落回模型自身缺省——temperature/seed 非可空）。"""
    kwargs: dict[str, Any] = {"provider": provider, "model": model, "api_key": api_key}
    if base_url:
        kwargs["base_url"] = str(base_url)
    if max_tokens is not None:
        kwargs["max_tokens"] = int(max_tokens)
    if temperature is not None:
        kwargs["temperature"] = float(temperature)
    if seed is not None:
        kwargs["seed"] = int(seed)
    return ProviderConfig(**kwargs)


def _finalize(providers: dict[str, ProviderConfig]) -> LLMConfig:
    """agent 回退 text、定 default。"""
    if "agent" not in providers and "text" in providers:
        providers["agent"] = providers["text"]
    if not providers:
        raise ConfigError("LLM 角色配置为空（至少需 text 或 vision 之一）")
    default = DEFAULT_ROLE if DEFAULT_ROLE in providers else next(iter(providers))
    return LLMConfig(default=default, providers=providers)


def _from_file(cfg: LLMFileConfig) -> LLMConfig:
    """llm.json → LLMConfig（provider 归一为线路协议分发键，厂商键存于文件展示层）。"""
    providers = {
        role: _build_provider(
            effective_protocol(rc.provider, rc.protocol),
            rc.model,
            rc.api_key,
            rc.base_url,
            rc.max_tokens,
            rc.temperature,
            rc.seed,
        )
        for role in ROLES
        if (rc := cfg.roles.get(role)) is not None
    }
    return _finalize(providers)


def _from_roles(roles: dict[str, dict[str, Any]]) -> LLMConfig:
    """平台拉取的角色配置 → LLMConfig（api_key 已解密）。"""
    providers: dict[str, ProviderConfig] = {}
    for role, cfg in roles.items():
        model = str(cfg.get("model") or "")
        api_key = str(cfg.get("api_key") or "")
        if not model or not api_key:
            continue
        providers[role] = _build_provider(
            cfg.get("provider") or "anthropic",
            model,
            api_key,
            cfg.get("base_url"),
            cfg.get("max_tokens"),
            cfg.get("temperature"),
            cfg.get("seed"),
        )
    return _finalize(providers)


def resolve_llm_config(
    path: Path | None = None,
    platform: LLMPlatform | None = None,
) -> LLMConfig:
    """解析 LLM 角色注册表：本地 llm.json 优先，平台拉取兜底。

    Raises:
        ConfigError: 两形态均不可用（报缺什么、在哪补）。
    """
    file_cfg = load_llm_file(path)
    if file_cfg is not None and any(file_cfg.roles.get(r) is not None for r in ROLES):
        return _from_file(file_cfg)
    platform = platform if platform is not None else LLMPlatform.from_env()
    if platform is not None:
        roles = platform.fetch()
        if roles:
            return _from_roles(roles)
    raise ConfigError(
        "LLM 配置不可用：本地未找到 ~/.agent_eval/llm.json（运行 `agent-eval models set` "
        "交互配置），且平台拉取未启用或无角色配置（需 AGENT_EVAL_HOST/AGENT_EVAL_API_KEY）"
    )


def llm_signature(config: LLMConfig) -> str:
    """解析后配置指纹（剔除 api_key）——评估缓存键用，替代原 yaml 文件字节 sha256。"""
    payload = {
        "default": config.default,
        "providers": {
            name: p.model_dump(exclude={"api_key"}, exclude_none=True)
            for name, p in sorted(config.providers.items())
        },
    }
    return "sha256:" + hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


__all__ = ["LLMPlatform", "llm_signature", "resolve_llm_config"]
