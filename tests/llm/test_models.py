"""LLM 数据模型测试 — Message, TokenUsage, LLMResponse, ProviderInfo, JudgeRecord。"""

from __future__ import annotations

from agent_eval.llm.models import (
    JudgeRecord,
    LLMResponse,
    Message,
    ProviderInfo,
    TokenUsage,
)


class TestTokenUsage:
    """TokenUsage 序列化往返测试。"""

    def test_defaults(self) -> None:
        tu = TokenUsage()
        assert tu.prompt_tokens == 0
        assert tu.completion_tokens == 0
        assert tu.total_tokens == 0

    def test_to_dict(self) -> None:
        tu = TokenUsage(prompt_tokens=100, completion_tokens=50, total_tokens=150)
        d = tu.to_dict()
        assert d == {
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "total_tokens": 150,
        }

    def test_from_dict(self) -> None:
        data = {"prompt_tokens": 200, "completion_tokens": 80, "total_tokens": 280}
        tu = TokenUsage.from_dict(data)
        assert tu.prompt_tokens == 200
        assert tu.completion_tokens == 80
        assert tu.total_tokens == 280

    def test_roundtrip(self) -> None:
        original = TokenUsage(prompt_tokens=500, completion_tokens=300, total_tokens=800)
        restored = TokenUsage.from_dict(original.to_dict())
        assert restored == original


class TestMessage:
    """Message 序列化往返测试。"""

    def test_to_dict(self) -> None:
        msg = Message(role="system", content="You are a judge.")
        d = msg.to_dict()
        assert d == {"role": "system", "content": "You are a judge."}

    def test_from_dict(self) -> None:
        data = {"role": "user", "content": "Evaluate this."}
        msg = Message.from_dict(data)
        assert msg.role == "user"
        assert msg.content == "Evaluate this."

    def test_roundtrip(self) -> None:
        original = Message(role="assistant", content='{"score": 8.5}')
        restored = Message.from_dict(original.to_dict())
        assert restored == original


class TestLLMResponse:
    """LLMResponse 序列化往返测试。"""

    def test_minimal(self) -> None:
        resp = LLMResponse(
            content="Hello", provider_name="deepseek_judge", model="deepseek-chat"
        )
        assert resp.usage is None
        assert resp.raw_response is None
        assert resp.duration_ms == 0.0

    def test_full_to_dict(self) -> None:
        resp = LLMResponse(
            content="Score: 8",
            provider_name="deepseek_judge",
            model="deepseek-chat",
            usage=TokenUsage(prompt_tokens=100, completion_tokens=50, total_tokens=150),
            raw_response={"id": "chatcmpl-123"},
            duration_ms=1200.5,
        )
        d = resp.to_dict()
        assert d["content"] == "Score: 8"
        assert d["provider_name"] == "deepseek_judge"
        assert d["model"] == "deepseek-chat"
        assert d["usage"]["total_tokens"] == 150
        assert d["raw_response"]["id"] == "chatcmpl-123"
        assert d["duration_ms"] == 1200.5

    def test_from_dict_with_usage(self) -> None:
        data = {
            "content": "Good",
            "provider_name": "deepseek_judge",
            "model": "deepseek-chat",
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            "duration_ms": 500.0,
        }
        resp = LLMResponse.from_dict(data)
        assert resp.usage is not None
        assert resp.usage.total_tokens == 15
        assert resp.duration_ms == 500.0

    def test_from_dict_without_usage(self) -> None:
        data = {
            "content": "OK",
            "provider_name": "test",
            "model": "test-model",
        }
        resp = LLMResponse.from_dict(data)
        assert resp.usage is None

    def test_roundtrip(self) -> None:
        original = LLMResponse(
            content="test",
            provider_name="p1",
            model="m1",
            usage=TokenUsage(100, 50, 150),
            raw_response={"key": "value"},
            duration_ms=999.0,
        )
        restored = LLMResponse.from_dict(original.to_dict())
        assert restored.content == original.content
        assert restored.provider_name == original.provider_name
        assert restored.model == original.model
        assert restored.usage == original.usage
        assert restored.duration_ms == original.duration_ms


class TestProviderInfo:
    """ProviderInfo 简单数据类测试。"""

    def test_fields(self) -> None:
        info = ProviderInfo(name="deepseek_judge", model="deepseek-chat", provider="deepseek")
        assert info.name == "deepseek_judge"
        assert info.model == "deepseek-chat"
        assert info.provider == "deepseek"


class TestJudgeRecord:
    """JudgeRecord 序列化往返测试。"""

    def test_defaults(self) -> None:
        record = JudgeRecord(
            judge_id="j1", constraint_id="c1", sample_id="s1",
            provider_name="p1", model="m1", template_id="t1",
        )
        assert record.temperature == 0.0
        assert record.seed == 42
        assert record.raw_response == ""
        assert record.parsed_scores == {}
        assert record.confidence == {}
        assert record.num_samples == 1
        assert record.token_usage is None

    def test_to_dict(self) -> None:
        record = JudgeRecord(
            judge_id="judge_001",
            constraint_id="soft.teaching_logic",
            sample_id="sample_01",
            provider_name="deepseek_judge",
            model="deepseek-chat",
            template_id="pedagogical_logic",
            temperature=0.0,
            seed=42,
            raw_response='{"score": 8}',
            parsed_scores={"score": 8},
            final_scores={"score": 8.0},
            confidence={"score": "high"},
            num_samples=3,
            total_duration_ms=3500.0,
            token_usage=TokenUsage(300, 150, 450),
            timestamp="2026-06-09T14:30:00",
        )
        d = record.to_dict()
        assert d["judge_id"] == "judge_001"
        assert d["token_usage"]["total_tokens"] == 450
        assert d["confidence"]["score"] == "high"

    def test_from_dict(self) -> None:
        data = {
            "judge_id": "judge_002",
            "constraint_id": "c2",
            "sample_id": "s2",
            "provider_name": "p2",
            "model": "m2",
            "template_id": "t2",
            "temperature": 0.5,
            "seed": 100,
            "raw_response": "test",
            "parsed_scores": {"a": 1},
            "final_scores": {"a": 1.0},
            "confidence": {"a": "low"},
            "num_samples": 5,
            "total_duration_ms": 1000.0,
            "token_usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            "timestamp": "2026-06-09T15:00:00",
        }
        record = JudgeRecord.from_dict(data)
        assert record.judge_id == "judge_002"
        assert record.token_usage is not None
        assert record.token_usage.total_tokens == 15
        assert record.confidence["a"] == "low"

    def test_roundtrip(self) -> None:
        original = JudgeRecord(
            judge_id="j3",
            constraint_id="c3",
            sample_id="s3",
            provider_name="p3",
            model="m3",
            template_id="t3",
            raw_response="resp",
            parsed_scores={"x": 1},
            final_scores={"x": 1.0},
            confidence={"x": "high"},
            num_samples=3,
            total_duration_ms=2000.0,
            token_usage=TokenUsage(100, 50, 150),
            timestamp="2026-06-09T16:00:00",
        )
        restored = JudgeRecord.from_dict(original.to_dict())
        assert restored.judge_id == original.judge_id
        assert restored.token_usage == original.token_usage
        assert restored.parsed_scores == original.parsed_scores
