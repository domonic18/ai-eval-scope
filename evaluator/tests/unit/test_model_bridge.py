"""model_bridge 单元测试（arch/03 §3.2 v4.6）——全部离线（伪 langchain 包）。"""

from __future__ import annotations

import sys
import types

import pytest

from agent_eval.agent.model_bridge import build_chat_model
from agent_eval.config.llm import LLMConfig, ProviderConfig
from agent_eval.core.exceptions import AgentError


def _install_fake(monkeypatch, module_name: str, cls_name: str) -> type:
    """注入伪 langchain provider 包，返回其记录构造参数的伪类。"""

    class FakeChatModel:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    fake = types.ModuleType(module_name)
    setattr(fake, cls_name, FakeChatModel)
    monkeypatch.setitem(sys.modules, module_name, fake)
    return FakeChatModel


def _config(providers: dict[str, ProviderConfig]) -> LLMConfig:
    return LLMConfig(default=next(iter(providers)), providers=providers)


def test_openai_protocol_bridge(monkeypatch) -> None:
    fake = _install_fake(monkeypatch, "langchain_openai", "ChatOpenAI")
    cfg = _config(
        {
            "remote": ProviderConfig(
                provider="openai",
                model="qwen-max",
                api_key="sk-plain",
                base_url="https://gw.example.com/v1",
            )
        }
    )
    model = build_chat_model("remote", llm_config=cfg)
    assert isinstance(model, fake)
    assert model.kwargs["model"] == "qwen-max"
    assert model.kwargs["base_url"] == "https://gw.example.com/v1"
    assert model.kwargs["api_key"].get_secret_value() == "sk-plain"


def test_deepseek_alias_default_base_url(monkeypatch) -> None:
    _install_fake(monkeypatch, "langchain_openai", "ChatOpenAI")
    cfg = _config(
        {"ds": ProviderConfig(provider="deepseek", model="deepseek-chat", api_key="sk-x")}
    )
    model = build_chat_model("ds", llm_config=cfg)
    assert model.kwargs["base_url"] == "https://api.deepseek.com/v1"


def test_model_override(monkeypatch) -> None:
    _install_fake(monkeypatch, "langchain_openai", "ChatOpenAI")
    cfg = _config(
        {"ds": ProviderConfig(provider="deepseek", model="deepseek-chat", api_key="sk-x")}
    )
    model = build_chat_model("ds", "deepseek-reasoner", llm_config=cfg)
    assert model.kwargs["model"] == "deepseek-reasoner"


def test_anthropic_protocol_bridge(monkeypatch) -> None:
    fake = _install_fake(monkeypatch, "langchain_anthropic", "ChatAnthropic")
    cfg = _config(
        {
            "kimi": ProviderConfig(
                provider="anthropic",
                model="kimi-latest",
                api_key="sk-anthropic",
                base_url="https://api.kimi.com/coding/",
            )
        }
    )
    model = build_chat_model("kimi", llm_config=cfg)
    assert isinstance(model, fake)
    assert model.kwargs["base_url"] == "https://api.kimi.com/coding/"


def test_unknown_provider_name_raises() -> None:
    cfg = _config({"ds": ProviderConfig(provider="deepseek", model="m", api_key="sk-x")})
    with pytest.raises(AgentError, match="未配置"):
        build_chat_model("ghost", llm_config=cfg)


def test_unsupported_protocol_raises() -> None:
    cfg = _config({"odd": ProviderConfig(provider="gemini", model="m", api_key="sk-x")})
    with pytest.raises(AgentError, match="不支持的 provider 协议"):
        build_chat_model("odd", llm_config=cfg)


def test_missing_dependency_hint(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "langchain_openai", None)
    cfg = _config({"ds": ProviderConfig(provider="deepseek", model="m", api_key="sk-x")})
    with pytest.raises(AgentError, match="agent-eval\\[agent\\]"):
        build_chat_model("ds", llm_config=cfg)
