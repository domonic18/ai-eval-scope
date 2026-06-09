"""DeepSeek 客户端 Mock 测试。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from agent_eval.llm.config import ProviderConfig
from agent_eval.llm.models import Message


def _make_mock_response(
    content: str = "Test response",
    prompt_tokens: int = 100,
    completion_tokens: int = 50,
    total_tokens: int = 150,
) -> MagicMock:
    """创建 mock OpenAI ChatCompletion 响应。"""
    mock_resp = MagicMock()
    mock_resp.choices = [MagicMock()]
    mock_resp.choices[0].message.content = content
    mock_resp.usage.prompt_tokens = prompt_tokens
    mock_resp.usage.completion_tokens = completion_tokens
    mock_resp.usage.total_tokens = total_tokens
    mock_resp.model_dump.return_value = {
        "id": "chatcmpl-test",
        "choices": [{"message": {"content": content}}],
    }
    return mock_resp


class TestDeepSeekClient:
    """DeepSeekClient 测试（全部 Mock openai 调用）。"""

    @patch("openai.OpenAI")
    def test_chat_basic(self, mock_openai_cls: MagicMock) -> None:
        """基本对话调用。"""
        mock_openai_cls.return_value.chat.completions.create.return_value = (
            _make_mock_response("Hello! How can I help?")
        )
        config = ProviderConfig(
            provider="deepseek",
            model="deepseek-chat",
            api_key="sk-test",
            base_url="https://api.deepseek.com/v1",
        )
        from agent_eval.llm.providers.deepseek import DeepSeekClient

        client = DeepSeekClient("ds_judge", config)
        messages = [Message(role="user", content="Hi")]
        resp = client.chat(messages)

        assert resp.content == "Hello! How can I help?"
        assert resp.provider_name == "ds_judge"
        assert resp.model == "deepseek-chat"
        assert resp.usage is not None
        assert resp.usage.total_tokens == 150
        assert resp.duration_ms > 0

    @patch("openai.OpenAI")
    def test_chat_with_kwargs_override(self, mock_openai_cls: MagicMock) -> None:
        """覆盖参数（temperature, seed, max_tokens）。"""
        mock_create = mock_openai_cls.return_value.chat.completions.create
        mock_create.return_value = _make_mock_response()

        config = ProviderConfig(
            provider="deepseek", model="deepseek-chat", api_key="sk-test"
        )
        from agent_eval.llm.providers.deepseek import DeepSeekClient

        client = DeepSeekClient("ds", config)
        client.chat(
            [Message(role="user", content="test")],
            temperature=0.5,
            seed=999,
            max_tokens=1024,
        )

        # 验证传给 API 的参数
        call_kwargs = mock_create.call_args[1]
        assert call_kwargs["temperature"] == 0.5
        assert call_kwargs["seed"] == 999
        assert call_kwargs["max_tokens"] == 1024

    @patch("openai.OpenAI")
    def test_chat_with_vision(self, mock_openai_cls: MagicMock) -> None:
        """多模态调用。"""
        mock_create = mock_openai_cls.return_value.chat.completions.create
        mock_create.return_value = _make_mock_response("Image shows a diagram.")

        config = ProviderConfig(
            provider="deepseek", model="deepseek-chat", api_key="sk-test"
        )
        from agent_eval.llm.providers.deepseek import DeepSeekClient

        client = DeepSeekClient("ds", config)
        messages = [Message(role="user", content="Describe this")]
        resp = client.chat_with_vision(messages, images=["http://img.url/pic.png"])

        assert resp.content == "Image shows a diagram."
        # 验证消息格式包含图片
        call_kwargs = mock_create.call_args[1]
        openai_msgs = call_kwargs["messages"]
        last_msg = openai_msgs[-1]
        assert isinstance(last_msg["content"], list)
        assert last_msg["content"][-1]["type"] == "image_url"

    @patch("openai.OpenAI")
    def test_chat_api_error(self, mock_openai_cls: MagicMock) -> None:
        """API 调用失败抛 LLMError。"""
        import openai as real_openai

        mock_openai_cls.return_value.chat.completions.create.side_effect = (
            real_openai.APIError(
                message="Server error",
                request=MagicMock(),
                body=None,
            )
        )

        config = ProviderConfig(
            provider="deepseek", model="deepseek-chat", api_key="sk-test"
        )
        from agent_eval.core.exceptions import LLMError
        from agent_eval.llm.providers.deepseek import DeepSeekClient

        client = DeepSeekClient("ds", config)
        with pytest.raises(LLMError, match="API 调用失败"):
            client.chat([Message(role="user", content="test")])

    @patch("openai.OpenAI")
    def test_provider_info(self, mock_openai_cls: MagicMock) -> None:
        """provider_info 属性。"""
        config = ProviderConfig(
            provider="deepseek", model="deepseek-chat", api_key="sk-test"
        )
        from agent_eval.llm.providers.deepseek import DeepSeekClient

        client = DeepSeekClient("my_ds", config)
        info = client.provider_info
        assert info.name == "my_ds"
        assert info.model == "deepseek-chat"
        assert info.provider == "deepseek"

    @patch("openai.OpenAI")
    def test_default_base_url(self, mock_openai_cls: MagicMock) -> None:
        """未指定 base_url 时使用默认值。"""
        config = ProviderConfig(
            provider="deepseek", model="m", api_key="k"
        )
        from agent_eval.llm.providers.deepseek import DeepSeekClient

        DeepSeekClient("ds", config)
        mock_openai_cls.assert_called_once()
        call_kwargs = mock_openai_cls.call_args[1]
        assert call_kwargs["base_url"] == "https://api.deepseek.com/v1"

    @patch("openai.OpenAI")
    def test_empty_response_content(self, mock_openai_cls: MagicMock) -> None:
        """空响应内容处理。"""
        mock_resp = _make_mock_response("")
        mock_resp.choices[0].message.content = None
        mock_openai_cls.return_value.chat.completions.create.return_value = mock_resp

        config = ProviderConfig(
            provider="deepseek", model="m", api_key="k"
        )
        from agent_eval.llm.providers.deepseek import DeepSeekClient

        client = DeepSeekClient("ds", config)
        resp = client.chat([Message(role="user", content="test")])
        assert resp.content == ""
