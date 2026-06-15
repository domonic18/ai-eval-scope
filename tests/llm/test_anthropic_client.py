"""AnthropicCompatClient Mock 测试。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from agent_eval.llm.config import ProviderConfig
from agent_eval.llm.models import Message


def _make_mock_response(
    text: str = "Anthropic response",
    input_tokens: int = 12,
    output_tokens: int = 8,
) -> MagicMock:
    """创建 mock Anthropic Messages 响应。"""
    mock_resp = MagicMock()
    block = MagicMock()
    block.text = text
    mock_resp.content = [block]
    mock_resp.usage.input_tokens = input_tokens
    mock_resp.usage.output_tokens = output_tokens
    mock_resp.model_dump.return_value = {"id": "msg-test", "content": [{"text": text}]}
    return mock_resp


class TestAnthropicCompatClient:
    """AnthropicCompatClient 测试（全部 Mock anthropic 调用）。"""

    @patch("anthropic.Anthropic")
    def test_chat_basic(self, mock_anth_cls: MagicMock) -> None:
        """基本对话调用：system 提升为顶层参数，content/usage 正确映射。"""
        mock_anth_cls.return_value.messages.create.return_value = _make_mock_response(
            "好的课件", 12, 8
        )
        config = ProviderConfig(
            provider="anthropic",
            model="kimi-2.6",
            api_key="sk-test",
            base_url="https://api.moonshot.cn/anthropic",
        )
        from agent_eval.llm.providers.anthropic import AnthropicCompatClient

        client = AnthropicCompatClient("kimi_vision", config)
        resp = client.chat(
            [
                Message(role="system", content="你是评审专家"),
                Message(role="user", content="评估这个"),
            ]
        )

        assert resp.content == "好的课件"
        assert resp.provider_name == "kimi_vision"
        assert resp.model == "kimi-2.6"
        assert client.provider_type == "anthropic"
        # usage 映射：input→prompt，output→completion，total=两者和
        assert resp.usage is not None
        assert resp.usage.prompt_tokens == 12
        assert resp.usage.completion_tokens == 8
        assert resp.usage.total_tokens == 20

        # system 是顶层参数，不在 messages 中
        call_kwargs = mock_anth_cls.return_value.messages.create.call_args.kwargs
        assert call_kwargs["system"] == "你是评审专家"
        assert all(m["role"] != "system" for m in call_kwargs["messages"])

    @patch("anthropic.Anthropic")
    def test_seed_dropped(self, mock_anth_cls: MagicMock) -> None:
        """Anthropic 不支持 seed，必须从 kwargs 丢弃。"""
        mock_anth_cls.return_value.messages.create.return_value = _make_mock_response()
        config = ProviderConfig(provider="anthropic", model="m", api_key="k")
        from agent_eval.llm.providers.anthropic import AnthropicCompatClient

        client = AnthropicCompatClient("k", config)
        client.chat([Message(role="user", content="x")], seed=999, temperature=0.3)

        call_kwargs = mock_anth_cls.return_value.messages.create.call_args.kwargs
        assert "seed" not in call_kwargs
        assert call_kwargs["temperature"] == 0.3

    @patch("anthropic.Anthropic")
    def test_max_tokens_always_passed(self, mock_anth_cls: MagicMock) -> None:
        """max_tokens 必填，始终透传（默认或覆盖）。"""
        mock_anth_cls.return_value.messages.create.return_value = _make_mock_response()
        config = ProviderConfig(provider="anthropic", model="m", api_key="k", max_tokens=2048)
        from agent_eval.llm.providers.anthropic import AnthropicCompatClient

        client = AnthropicCompatClient("k", config)
        client.chat([Message(role="user", content="x")])
        call_kwargs = mock_anth_cls.return_value.messages.create.call_args.kwargs
        assert call_kwargs["max_tokens"] == 2048

    @patch("anthropic.Anthropic")
    def test_chat_with_vision_data_uri(self, mock_anth_cls: MagicMock) -> None:
        """多模态调用：data URI 解析为 base64 image block。"""
        mock_anth_cls.return_value.messages.create.return_value = _make_mock_response("排版良好")
        config = ProviderConfig(provider="anthropic", model="kimi-2.6", api_key="k")
        from agent_eval.llm.providers.anthropic import AnthropicCompatClient

        client = AnthropicCompatClient("k", config)
        resp = client.chat_with_vision(
            [Message(role="user", content="看图")],
            images=["data:image/png;base64,QUJDREU="],
        )
        assert resp.content == "排版良好"

        call_kwargs = mock_anth_cls.return_value.messages.create.call_args.kwargs
        last_msg = call_kwargs["messages"][-1]
        assert isinstance(last_msg["content"], list)
        # 文本块 + 图片块
        assert last_msg["content"][0] == {"type": "text", "text": "看图"}
        img_block = last_msg["content"][1]
        assert img_block["type"] == "image"
        assert img_block["source"]["type"] == "base64"
        assert img_block["source"]["media_type"] == "image/png"
        assert img_block["source"]["data"] == "QUJDREU="

    @patch("anthropic.Anthropic")
    def test_chat_with_vision_url(self, mock_anth_cls: MagicMock) -> None:
        """多模态调用：URL 图片走 url source。"""
        mock_anth_cls.return_value.messages.create.return_value = _make_mock_response()
        config = ProviderConfig(provider="anthropic", model="kimi-2.6", api_key="k")
        from agent_eval.llm.providers.anthropic import AnthropicCompatClient

        client = AnthropicCompatClient("k", config)
        client.chat_with_vision(
            [Message(role="user", content="看图")],
            images=["https://example.com/a.png"],
        )
        call_kwargs = mock_anth_cls.return_value.messages.create.call_args.kwargs
        img_block = call_kwargs["messages"][-1]["content"][1]
        assert img_block["source"]["type"] == "url"
        assert img_block["source"]["url"] == "https://example.com/a.png"

    @patch("anthropic.Anthropic")
    def test_api_error(self, mock_anth_cls: MagicMock) -> None:
        """API 调用失败抛 LLMError。"""
        import anthropic as real_anthropic

        mock_anth_cls.return_value.messages.create.side_effect = real_anthropic.APIStatusError(
            message="Bad request",
            response=MagicMock(),
            body=None,
        )
        config = ProviderConfig(provider="anthropic", model="m", api_key="k")
        from agent_eval.core.exceptions import LLMError
        from agent_eval.llm.providers.anthropic import AnthropicCompatClient

        client = AnthropicCompatClient("k", config)
        with pytest.raises(LLMError, match="API 调用失败"):
            client.chat([Message(role="user", content="x")])
