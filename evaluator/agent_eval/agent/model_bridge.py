"""llm_config → LangChain ChatModel 桥接（arch/03 §3.2 v4.6）。

执行 Agent 与评估 LLM 共用同一配置源（llm_config.yaml，见 arch/05）：按 provider
协议构造 ChatOpenAI（deepseek/openai 兼容协议）或 ChatAnthropic（Anthropic 兼容
协议），带 base_url/api_key/model——模型无关，DeepAgents 底座直接消费。
langchain 相关包为 [agent] optional extra，此处惰性导入。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_eval.config import ConfigLoader
from agent_eval.config.llm import LLMConfig, resolve_api_key
from agent_eval.config.paths import paths
from agent_eval.core.exceptions import AgentError

# deepseek 别名未指定 base_url 时预置端点（与 llm/providers/openai_compat.py 惯例一致）
_DEEPSEEK_DEFAULT_BASE_URL = "https://api.deepseek.com/v1"


def discover_llm_config_path(config_path: Path | str | None = None) -> Path:
    """定位 llm_config.yaml：显式路径 → CWD → 包内 assets/configs。"""
    if config_path is not None:
        return Path(config_path)
    cwd_cfg = Path.cwd() / "llm_config.yaml"
    if cwd_cfg.exists():
        return cwd_cfg
    packaged = paths.configs_dir / "llm_config.yaml"
    return packaged


def build_chat_model(
    provider_name: str,
    model: str | None = None,
    *,
    llm_config: LLMConfig | None = None,
    config_path: Path | str | None = None,
) -> Any:
    """按 llm_config 构造 LangChain ChatModel（双协议桥接）。

    Args:
        provider_name: llm_config.yaml 中的 provider 配置名（如 "deepseek"/"kimi"）。
        model: 覆盖 provider 默认模型（可选）。
        llm_config: 已加载的 LLMConfig（可选；缺省自动发现并加载）。
        config_path: llm_config.yaml 路径（可选；缺省走 discover_llm_config_path）。

    Returns:
        LangChain ChatModel 实例（ChatOpenAI / ChatAnthropic）。

    Raises:
        AgentError: provider 名不存在、协议不支持或缺少 [agent] extra 依赖。
    """
    if llm_config is None:
        path = discover_llm_config_path(config_path)
        if not path.exists():
            raise AgentError(
                f"未找到 llm_config.yaml（查找顺序: 显式路径 → CWD → 包内 assets/configs）: {path}",
                details={"path": str(path)},
            )
        llm_config = ConfigLoader.load_llm_config(path)

    if provider_name not in llm_config.providers:
        raise AgentError(
            f"llm_config 中不存在 provider: {provider_name!r}",
            details={"available": sorted(llm_config.providers)},
        )
    provider = llm_config.providers[provider_name]

    api_key = resolve_api_key(provider.api_key)
    model_id = model or provider.model

    if provider.provider in ("deepseek", "openai"):
        try:
            from langchain_openai import ChatOpenAI
        except ImportError:
            raise AgentError(
                "构建 ChatOpenAI 需要 langchain-openai。请执行: pip install 'agent-eval[agent]'",
                details={"missing_module": "langchain_openai"},
            ) from None
        base_url = provider.base_url
        if not base_url and provider.provider == "deepseek":
            base_url = _DEEPSEEK_DEFAULT_BASE_URL
        return ChatOpenAI(
            model=model_id,
            api_key=api_key,
            base_url=base_url,
            temperature=provider.temperature,
            max_tokens=provider.max_tokens,
        )

    if provider.provider == "anthropic":
        try:
            from langchain_anthropic import ChatAnthropic
        except ImportError:
            raise AgentError(
                "构建 ChatAnthropic 需要 langchain-anthropic。请执行: pip install 'agent-eval[agent]'",
                details={"missing_module": "langchain_anthropic"},
            ) from None
        kwargs: dict[str, Any] = {
            "model": model_id,
            "api_key": api_key,
            "temperature": provider.temperature,
        }
        if provider.base_url:
            kwargs["base_url"] = provider.base_url
        return ChatAnthropic(**kwargs)

    raise AgentError(
        f"不支持的 provider 协议: {provider.provider!r}",
        details={"supported_protocols": ["deepseek", "openai", "anthropic"]},
    )


__all__ = ["build_chat_model", "discover_llm_config_path"]
