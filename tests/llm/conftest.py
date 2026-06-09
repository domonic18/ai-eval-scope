"""LLM 测试共享 fixtures。"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_eval.llm.config import LLMConfig, ProviderConfig

FIXTURES = Path(__file__).parent.parent / "fixtures"


@pytest.fixture
def deepseek_config() -> ProviderConfig:
    """单个 DeepSeek Provider 配置。"""
    return ProviderConfig(
        provider="deepseek",
        model="deepseek-chat",
        api_key="test-api-key",
        base_url="https://api.deepseek.com/v1",
        max_tokens=4096,
    )


@pytest.fixture
def llm_config() -> LLMConfig:
    """多 Provider LLM 配置。"""
    return LLMConfig(
        default="deepseek_judge",
        providers={
            "deepseek_judge": ProviderConfig(
                provider="deepseek",
                model="deepseek-chat",
                api_key="test-key-ds",
                base_url="https://api.deepseek.com/v1",
            ),
            "openai_judge": ProviderConfig(
                provider="openai",
                model="gpt-4",
                api_key="test-key-oai",
                base_url="https://api.openai.com/v1",
            ),
        },
    )


@pytest.fixture
def prompts_dir(tmp_path: Path) -> Path:
    """创建临时 Prompt 模板目录。"""
    prompts = tmp_path / "prompts"
    prompts.mkdir()
    return prompts
