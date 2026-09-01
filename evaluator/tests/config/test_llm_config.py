"""LLM 配置模型测试 — ProviderConfig, LLMConfig, 各默认值。

（resolve_api_key 随 llm_config.yaml 链路移除而废弃，a00775a 一次性
删除不留兼容——对应测试同步清理。）
"""

from __future__ import annotations

import pytest

from agent_eval.config import (
    JUDGE_DEFAULTS,
    JUDGE_ID_DATETIME_FORMAT,
    JUDGE_RECORD_DEFAULTS,
    LANGFUSE_DEFAULTS,
    STABILITY_DEFAULTS,
    STRUCTURED_OUTPUT_DEFAULTS,
    LLMConfig,
    ProviderConfig,
)


class TestProviderConfig:
    """ProviderConfig Pydantic 校验测试。"""

    def test_minimal(self) -> None:
        """最少必填字段。"""
        cfg = ProviderConfig(provider="deepseek", model="deepseek-chat", api_key="sk-test")
        assert cfg.base_url is None
        assert cfg.max_tokens == 4096
        assert cfg.temperature == 0.0
        assert cfg.seed == 42

    def test_full(self) -> None:
        """全部字段。"""
        cfg = ProviderConfig(
            provider="deepseek",
            model="deepseek-chat",
            api_key="sk-test",
            base_url="https://custom.api.com/v1",
            max_tokens=8192,
            temperature=0.3,
            seed=100,
            extra_params={"top_p": 0.9},
        )
        assert cfg.base_url == "https://custom.api.com/v1"
        assert cfg.max_tokens == 8192
        assert cfg.temperature == 0.3

    def test_temperature_validation(self) -> None:
        """温度范围校验 [0, 2]。"""
        with pytest.raises(Exception):
            ProviderConfig(provider="deepseek", model="m", api_key="k", temperature=3.0)

    def test_extra_fields_allowed(self) -> None:
        """允许额外字段（model_config extra=allow）。"""
        cfg = ProviderConfig(
            provider="deepseek",
            model="m",
            api_key="k",
            custom_field="value",  # type: ignore[call-arg]
        )
        assert cfg.custom_field == "value"  # type: ignore[attr-defined]

    def test_serialization_roundtrip(self) -> None:
        """序列化往返。"""
        cfg = ProviderConfig(
            provider="deepseek",
            model="deepseek-chat",
            api_key="sk-test",
            base_url="https://api.deepseek.com/v1",
            max_tokens=4096,
        )
        data = cfg.model_dump()
        restored = ProviderConfig.model_validate(data)
        assert restored.provider == cfg.provider
        assert restored.model == cfg.model


class TestLLMConfig:
    """LLMConfig Pydantic 校验测试。"""

    def test_basic(self, llm_config: LLMConfig) -> None:
        """基本配置。"""
        assert llm_config.default == "deepseek_judge"
        assert len(llm_config.providers) == 2
        assert "deepseek_judge" in llm_config.providers
        assert "openai_judge" in llm_config.providers

    def test_from_yaml_dict(self) -> None:
        """从 YAML 加载的 dict 构造。"""
        data = {
            "default": "ds",
            "providers": {
                "ds": {
                    "provider": "deepseek",
                    "model": "deepseek-chat",
                    "api_key": "sk-yaml",
                    "base_url": "https://api.deepseek.com/v1",
                }
            },
        }
        config = LLMConfig.model_validate(data)
        assert config.default == "ds"
        assert config.providers["ds"].model == "deepseek-chat"

    def test_serialization_roundtrip(self, llm_config: LLMConfig) -> None:
        """序列化往返。"""
        data = llm_config.model_dump()
        restored = LLMConfig.model_validate(data)
        assert restored.default == llm_config.default
        assert set(restored.providers.keys()) == set(llm_config.providers.keys())


class TestDefaults:
    """LLM Judge 相关默认参数集中配置测试。"""

    def test_judge_defaults(self) -> None:
        """Judge 模板默认参数。"""
        assert JUDGE_DEFAULTS.temperature == 0.0
        assert JUDGE_DEFAULTS.seed == 42
        assert JUDGE_DEFAULTS.num_samples == 3
        assert JUDGE_DEFAULTS.score_range == (0.0, 10.0)

    def test_stability_defaults(self) -> None:
        """稳定性控制器默认参数。"""
        assert STABILITY_DEFAULTS.num_samples == 3
        assert STABILITY_DEFAULTS.stddev_threshold == 1.5

    def test_structured_output_defaults(self) -> None:
        """结构化输出解析器默认参数。"""
        assert STRUCTURED_OUTPUT_DEFAULTS.max_retries == 3

    def test_langfuse_defaults(self) -> None:
        """Langfuse 默认参数。"""
        assert LANGFUSE_DEFAULTS.host == "https://cloud.langfuse.com"

    def test_judge_record_defaults(self) -> None:
        """JudgeRecord 默认参数。"""
        assert JUDGE_RECORD_DEFAULTS.temperature == 0.0
        assert JUDGE_RECORD_DEFAULTS.seed == 42
        assert JUDGE_RECORD_DEFAULTS.num_samples == 1

    def test_judge_id_datetime_format(self) -> None:
        """Judge ID 时间戳格式。"""
        assert JUDGE_ID_DATETIME_FORMAT == "%Y%m%d_%H%M%S"
