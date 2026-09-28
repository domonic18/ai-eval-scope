"""DecisionClient 单测 — httpx.MockTransport 全离线（禁联网纪律）。

覆盖：成功契约（URL/body/鉴权头/noul 解析/resolved model）、瞬时错误重试一次
（429/5xx/超时）、重试耗尽分级抛出、401 即失败不重试、响应畸形（缺 noul/非数值/
越界）、默认端点、api_key 零泄漏（异常 repr 不含密钥）。
"""

from __future__ import annotations

import json
from collections.abc import Callable

import httpx
import pytest

from agent_eval.config.llm import ProviderConfig
from agent_eval.core.exceptions import (
    DecisionResponseError,
    LLMAuthError,
    LLMError,
    LLMNetworkError,
    LLMRateLimitError,
)
from agent_eval.llm.decision import DecisionClient, NoulQuestion

_API_KEY = "sk-decision-unit-test-0000"
_QUESTION = NoulQuestion(
    name="is_real_error",
    instructions="判定疑似错误是否成立",
    criteria={"true": "成立", "false": "误触"},
)


def _ok_response(name: str = "is_real_error") -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "model": "typesafe/jev-1.13-20260917",
            "answers": {name: {"noul": 0.92}},
            "usage": {"input_tokens": 494, "output_tokens": 22, "cost": 2.07e-05},
        },
    )


def _make_client(
    handler: Callable[[httpx.Request], httpx.Response],
    base_url: str | None = "https://router.test/api",
) -> tuple[DecisionClient, list[httpx.Request]]:
    calls: list[httpx.Request] = []

    def _recording(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return handler(request)

    config = ProviderConfig(
        provider="openai",
        model="typesafe/jev-1.13",
        api_key=_API_KEY,
        base_url=base_url,
        timeout_sec=5.0,
    )
    return DecisionClient("decision", config, transport=httpx.MockTransport(_recording)), calls


@pytest.fixture(autouse=True)
def _no_retry_delay(monkeypatch: pytest.MonkeyPatch) -> None:
    """重试退避归零（单元测试不等 0.5s 墙钟）。"""
    monkeypatch.setattr("agent_eval.llm.decision._RETRY_DELAY_SEC", 0.0)


class TestNoulSuccess:
    def test_success_contract(self) -> None:
        client, calls = _make_client(lambda _r: _ok_response())
        ans = client.noul(_QUESTION, {"text": "课件原文", "claim": "疑似错误"})
        assert ans.p_yes == 0.92
        assert ans.question_name == "is_real_error"
        assert ans.model == "typesafe/jev-1.13-20260917"  # 服务端 resolved 快照
        assert ans.latency_ms > 0
        assert ans.raw["usage"]["cost"] == pytest.approx(2.07e-05)
        req = calls[0]
        assert req.method == "POST"
        assert str(req.url) == "https://router.test/api/alpha/decisions"
        assert req.headers["authorization"] == f"Bearer {_API_KEY}"
        body = json.loads(req.content)
        assert body["model"] == "typesafe/jev-1.13"
        assert body["state"] == {"text": "课件原文", "claim": "疑似错误"}
        q = body["questions"]["is_real_error"]
        assert q["type"] == "noul"
        assert q["criteria"] == {"true": "成立", "false": "误触"}

    def test_default_base_url_when_unset(self) -> None:
        client, calls = _make_client(lambda _r: _ok_response(), base_url=None)
        client.noul(_QUESTION, {"text": "t"})
        assert str(calls[0].url) == "https://openrouter.ai/api/alpha/decisions"

    def test_question_body_is_defensive_copy(self) -> None:
        """criteria 拷贝进 wire body——调用方事后改问题对象不影响已发请求。"""
        sent: list[dict] = []

        def handler(request: httpx.Request) -> httpx.Response:
            sent.append(json.loads(request.content))
            return _ok_response(name="q")

        question = NoulQuestion("q", "判", {"true": "a", "false": "b"})
        client, _ = _make_client(handler)
        client.noul(question, {"text": "t"})
        question.criteria["true"] = "tampered"
        assert sent[0]["questions"]["q"]["criteria"]["true"] == "a"


class TestTransientRetry:
    def test_rate_limit_then_success_retries_once(self) -> None:
        responses = [httpx.Response(429), _ok_response()]
        client, calls = _make_client(lambda _r: responses.pop(0))
        ans = client.noul(_QUESTION, {"text": "t"})
        assert ans.p_yes == 0.92
        assert len(calls) == 2  # 初次 + 重试 1 次

    def test_server_error_then_success_retries_once(self) -> None:
        responses = [httpx.Response(503), _ok_response()]
        client, calls = _make_client(lambda _r: responses.pop(0))
        assert client.noul(_QUESTION, {"text": "t"}).p_yes == 0.92
        assert len(calls) == 2

    @pytest.mark.parametrize("status,exc_type", [(429, LLMRateLimitError), (502, LLMNetworkError)])
    def test_retry_exhausted_raises_graded(self, status: int, exc_type: type[LLMError]) -> None:
        client, calls = _make_client(lambda _r: httpx.Response(status))
        with pytest.raises(exc_type):
            client.noul(_QUESTION, {"text": "t"})
        assert len(calls) == 2  # 耗尽后抛出，不无限重试

    def test_timeout_retried_then_network_error(self) -> None:
        def handler(_request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectTimeout("timed out")

        client, calls = _make_client(handler)
        with pytest.raises(LLMNetworkError):
            client.noul(_QUESTION, {"text": "t"})
        assert len(calls) == 2

    def test_auth_failure_raises_immediately_without_retry(self) -> None:
        client, calls = _make_client(lambda _r: httpx.Response(401))
        with pytest.raises(LLMAuthError):
            client.noul(_QUESTION, {"text": "t"})
        assert len(calls) == 1  # 鉴权失败不属瞬时错误


class TestMalformedResponse:
    def test_missing_answers_raises_response_error(self) -> None:
        client, _ = _make_client(lambda _r: httpx.Response(200, json={"model": "x"}))
        with pytest.raises(DecisionResponseError, match="noul"):
            client.noul(_QUESTION, {"text": "t"})

    def test_non_numeric_noul_raises(self) -> None:
        body = {"answers": {"is_real_error": {"noul": "high"}}}
        client, _ = _make_client(lambda _r: httpx.Response(200, json=body))
        with pytest.raises(DecisionResponseError):
            client.noul(_QUESTION, {"text": "t"})

    def test_out_of_range_noul_raises(self) -> None:
        body = {"answers": {"is_real_error": {"noul": 1.5}}}
        client, _ = _make_client(lambda _r: httpx.Response(200, json=body))
        with pytest.raises(DecisionResponseError, match="越界"):
            client.noul(_QUESTION, {"text": "t"})

    def test_decision_errors_are_llm_errors(self) -> None:
        """分级异常均落 LLMError 族——过滤层单点捕获（判定线故障时放行降级，不阻塞评测）。"""
        assert issubclass(DecisionResponseError, LLMError)


class TestHygiene:
    @pytest.mark.parametrize(
        "handler_factory",
        [
            lambda: lambda _r: httpx.Response(401),
            lambda: lambda _r: httpx.Response(200, json={}),
        ],
        ids=["auth-fail", "malformed"],
    )
    def test_api_key_never_leaks_in_error(self, handler_factory: Callable) -> None:
        client, _ = _make_client(handler_factory())
        with pytest.raises(LLMError) as ei:
            client.noul(_QUESTION, {"text": "t"})
        assert _API_KEY not in str(ei.value)
        assert _API_KEY not in repr(ei.value)
