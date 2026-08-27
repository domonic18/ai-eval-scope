"""角色注册表 → LangChain ChatModel 桥接（arch/03 §3.2 v4.6；LLM② 切双形态解析）。

执行 Agent 与评估 LLM 共用同一配置源（固定三角色注册表，arch/13 §19.2）：按
provider 协议构造 ChatOpenAI（deepseek/openai 兼容协议）或 ChatAnthropic（Anthropic
兼容协议），带 base_url/api_key/model——模型无关，DeepAgents 底座直接消费。
langchain 相关包为 [agent] optional extra，此处惰性导入。
"""

from __future__ import annotations

from typing import Any

from agent_eval.config.llm import LLMConfig
from agent_eval.config.llm_resolution import resolve_llm_config
from agent_eval.core.exceptions import AgentError

# deepseek 别名未指定 base_url 时预置端点（与 llm/providers/openai_compat.py 惯例一致）
_DEEPSEEK_DEFAULT_BASE_URL = "https://api.deepseek.com/v1"


def build_chat_model(
    role: str,
    model: str | None = None,
    *,
    llm_config: LLMConfig | None = None,
) -> Any:
    """按角色注册表构造 LangChain ChatModel（双协议桥接）。

    Args:
        role: 角色名（text / vision / agent；agent 未配置时解析器已回退 text）。
        model: 覆盖角色默认模型（可选）。
        llm_config: 已解析的 LLMConfig（可选；缺省走 resolve_llm_config 双形态解析：
            本地 llm.json 优先，平台拉取兜底）。

    Returns:
        LangChain ChatModel 实例（ChatOpenAI / ChatAnthropic）。

    Raises:
        AgentError: 角色未配置、协议不支持或缺少 [agent] extra 依赖。
    """
    if llm_config is None:
        llm_config = resolve_llm_config()
    if role not in llm_config.providers:
        raise AgentError(
            f"LLM 角色 {role!r} 未配置（可选: {sorted(llm_config.providers)}）；"
            "运行 agent-eval models login（CLI）或在平台 admin 配置（云端）",
            details={"available": sorted(llm_config.providers), "role": role},
        )
    provider = llm_config.providers[role]
    api_key = provider.api_key
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


__all__ = ["build_chat_model"]
