"""测试 agent_eval.llm.tracing — Langfuse 追踪模块。"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from agent_eval.llm.tracing import (
    create_trace,
    flush_traces,
    get_langfuse,
    is_tracing_enabled,
    reset_langfuse,
)


@pytest.fixture(autouse=True)
def _reset_singleton():
    """每个测试前后重置 Langfuse 单例。"""
    reset_langfuse()
    yield
    reset_langfuse()


def _make_mock_langfuse():
    """创建一个 mock Langfuse 客户端及其实例。"""
    mock_instance = MagicMock()
    mock_cls = MagicMock(return_value=mock_instance)
    return mock_cls, mock_instance


def _setup_env_and_mock():
    """设置环境变量并 mock Langfuse 构造函数。"""
    mock_cls, mock_instance = _make_mock_langfuse()
    cm = patch.dict(
        os.environ,
        {"LANGFUSE_PUBLIC_KEY": "pk-lf-test", "LANGFUSE_SECRET_KEY": "sk-lf-test"},
    )
    pm = patch("langfuse.Langfuse", mock_cls)
    return mock_cls, mock_instance, cm, pm


# ─── get_langfuse ───


class TestGetLangfuse:
    """测试 get_langfuse() 单例初始化逻辑。"""

    def test_returns_none_without_env_vars(self) -> None:
        """未设置环境变量时返回 None。"""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("LANGFUSE_PUBLIC_KEY", None)
            os.environ.pop("LANGFUSE_SECRET_KEY", None)
            result = get_langfuse()
        assert result is None

    def test_returns_none_with_empty_keys(self) -> None:
        """环境变量为空字符串时返回 None。"""
        with patch.dict(os.environ, {"LANGFUSE_PUBLIC_KEY": "", "LANGFUSE_SECRET_KEY": ""}):
            result = get_langfuse()
        assert result is None

    def test_returns_none_with_only_public_key(self) -> None:
        """只有 public key 时返回 None。"""
        with patch.dict(os.environ, {"LANGFUSE_PUBLIC_KEY": "pk-lf-test", "LANGFUSE_SECRET_KEY": ""}):
            result = get_langfuse()
        assert result is None

    def test_returns_client_with_valid_keys(self) -> None:
        """双 key 齐全时返回 Langfuse 客户端实例。"""
        mock_cls, mock_instance, cm, pm = _setup_env_and_mock()
        with cm, pm:
            result = get_langfuse()

        assert result is mock_instance
        mock_cls.assert_called_once_with(
            public_key="pk-lf-test",
            secret_key="sk-lf-test",
            host="https://cloud.langfuse.com",
        )

    def test_custom_host(self) -> None:
        """LANGFUSE_HOST 环境变量生效。"""
        mock_cls, mock_instance = _make_mock_langfuse()
        with (
            patch.dict(
                os.environ,
                {
                    "LANGFUSE_PUBLIC_KEY": "pk-lf-test",
                    "LANGFUSE_SECRET_KEY": "sk-lf-test",
                    "LANGFUSE_HOST": "http://localhost:3000",
                },
            ),
            patch("langfuse.Langfuse", mock_cls),
        ):
            result = get_langfuse()

        assert result is mock_instance
        mock_cls.assert_called_once_with(
            public_key="pk-lf-test",
            secret_key="sk-lf-test",
            host="http://localhost:3000",
        )

    def test_singleton_reuse(self) -> None:
        """第二次调用返回同一实例（不再调用构造函数）。"""
        mock_cls, _, cm, pm = _setup_env_and_mock()
        with cm, pm:
            first = get_langfuse()
            second = get_langfuse()

        assert first is second
        assert mock_cls.call_count == 1  # 只构造一次

    def test_import_failure_returns_none(self) -> None:
        """Langfuse SDK 导入失败时返回 None 且不抛异常。"""
        with (
            patch.dict(
                os.environ,
                {"LANGFUSE_PUBLIC_KEY": "pk-lf-test", "LANGFUSE_SECRET_KEY": "sk-lf-test"},
            ),
            patch("langfuse.Langfuse", side_effect=ImportError("no langfuse")),
        ):
            result = get_langfuse()

        assert result is None


# ─── is_tracing_enabled ───


class TestIsTracingEnabled:
    """测试 is_tracing_enabled() 判断。"""

    def test_disabled_without_env(self) -> None:
        """无环境变量时禁用。"""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("LANGFUSE_PUBLIC_KEY", None)
            os.environ.pop("LANGFUSE_SECRET_KEY", None)
            assert is_tracing_enabled() is False

    def test_enabled_with_valid_keys(self) -> None:
        """有效环境变量时启用。"""
        mock_cls, _, cm, pm = _setup_env_and_mock()
        with cm, pm:
            assert is_tracing_enabled() is True


# ─── flush_traces ───


class TestFlushTraces:
    """测试 flush_traces() 行为。"""

    def test_noop_when_disabled(self) -> None:
        """未启用时调用不报错。"""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("LANGFUSE_PUBLIC_KEY", None)
            os.environ.pop("LANGFUSE_SECRET_KEY", None)
            reset_langfuse()
            flush_traces()  # 应无异常

    def test_calls_flush_when_enabled(self) -> None:
        """已启用时调用客户端 flush。"""
        mock_cls, mock_instance, cm, pm = _setup_env_and_mock()
        with cm, pm:
            get_langfuse()  # 初始化单例
            flush_traces()

        mock_instance.flush.assert_called_once()


# ─── create_trace ───


class TestCreateTrace:
    """测试 create_trace() 创建 Langfuse Trace。"""

    def test_returns_none_when_disabled(self) -> None:
        """未启用时返回 None。"""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("LANGFUSE_PUBLIC_KEY", None)
            os.environ.pop("LANGFUSE_SECRET_KEY", None)
            reset_langfuse()
            result = create_trace("judge:test")

        assert result is None

    def test_creates_trace_when_enabled(self) -> None:
        """启用时创建 trace 并返回 (span, trace_ctx) 元组。"""
        mock_span = MagicMock()

        mock_cls, mock_instance, cm, pm = _setup_env_and_mock()
        mock_instance.create_trace_id.return_value = "abc123"
        mock_instance.start_observation.return_value = mock_span

        with cm, pm:
            result = create_trace("judge:test", metadata={"key": "val"})

        assert result is not None
        span, trace_ctx = result
        assert span is mock_span
        assert trace_ctx == {"trace_id": "abc123"}

        mock_instance.create_trace_id.assert_called_once_with(seed="judge:test")
        mock_instance.start_observation.assert_called_once_with(
            name="judge:test",
            trace_context={"trace_id": "abc123"},
            as_type="span",
            metadata={"key": "val"},
        )


# ─── reset_langfuse ───


class TestResetLangfuse:
    """测试 reset_langfuse() 重置行为。"""

    def test_resets_singleton(self) -> None:
        """重置后再次调用 get_langfuse() 会重新创建客户端。"""
        mock_cls, _, cm, pm = _setup_env_and_mock()
        with cm, pm:
            first = get_langfuse()

        assert first is not None
        reset_langfuse()

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("LANGFUSE_PUBLIC_KEY", None)
            os.environ.pop("LANGFUSE_SECRET_KEY", None)
            assert get_langfuse() is None
