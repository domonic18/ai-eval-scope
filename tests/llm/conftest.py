"""LLM 测试共享 fixtures。"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_eval.config import ProviderConfig

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
def prompts_dir(tmp_path: Path) -> Path:
    """创建临时 Prompt 模板目录。"""
    prompts = tmp_path / "prompts"
    prompts.mkdir()
    return prompts
