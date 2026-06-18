"""StructuredOutputParser 测试 — JSON 提取与 Schema 验证。"""

from __future__ import annotations

import pytest

from agent_eval.core.exceptions import LLMResponseError
from agent_eval.llm.judge.structured_output import StructuredOutputParser

SIMPLE_SCHEMA = {
    "type": "object",
    "properties": {
        "score": {"type": "number"},
        "reason": {"type": "string"},
    },
    "required": ["score", "reason"],
}


class TestStructuredOutputParser:
    """StructuredOutputParser 测试。"""

    def test_extract_bare_json(self) -> None:
        """提取裸 JSON 对象。"""
        parser = StructuredOutputParser()
        raw = '{"score": 8.5, "reason": "Good content"}'
        result = parser.parse(raw, SIMPLE_SCHEMA)
        assert result["score"] == 8.5
        assert result["reason"] == "Good content"

    def test_extract_json_code_block(self) -> None:
        """提取 ```json ... ``` 包裹的 JSON。"""
        parser = StructuredOutputParser()
        raw = 'Here is the evaluation:\n```json\n{"score": 7.0, "reason": "Decent"}\n```'
        result = parser.parse(raw, SIMPLE_SCHEMA)
        assert result["score"] == 7.0

    def test_extract_code_block_no_language(self) -> None:
        """提取 ``` ... ``` 包裹的 JSON（无语言标记）。"""
        parser = StructuredOutputParser()
        raw = 'Result:\n```\n{"score": 9.0, "reason": "Excellent"}\n```'
        result = parser.parse(raw, SIMPLE_SCHEMA)
        assert result["score"] == 9.0

    def test_schema_validation_pass(self) -> None:
        """Schema 验证通过。"""
        parser = StructuredOutputParser()
        result = parser.parse(
            '{"score": 5, "reason": "Average"}',
            SIMPLE_SCHEMA,
        )
        assert result == {"score": 5, "reason": "Average"}

    def test_schema_validation_fail_missing_required(self) -> None:
        """Schema 验证失败 — 缺少必填字段。"""
        parser = StructuredOutputParser()
        with pytest.raises(LLMResponseError, match="验证失败"):
            parser.parse('{"score": 5}', SIMPLE_SCHEMA)

    def test_schema_validation_fail_wrong_type(self) -> None:
        """Schema 验证失败 — 类型错误。"""
        parser = StructuredOutputParser()
        with pytest.raises(LLMResponseError, match="验证失败"):
            parser.parse(
                '{"score": "not_a_number", "reason": "test"}',
                SIMPLE_SCHEMA,
            )

    def test_empty_response(self) -> None:
        """空响应抛 LLMResponseError。"""
        parser = StructuredOutputParser()
        with pytest.raises(LLMResponseError, match="为空"):
            parser.parse("", SIMPLE_SCHEMA)

    def test_no_json_found(self) -> None:
        """无法提取 JSON 时抛 LLMResponseError。"""
        parser = StructuredOutputParser()
        with pytest.raises(LLMResponseError, match="无法从"):
            parser.parse("This is just plain text without any JSON.", SIMPLE_SCHEMA)

    def test_invalid_json(self) -> None:
        """无效 JSON 抛 LLMResponseError。"""
        parser = StructuredOutputParser()
        with pytest.raises(LLMResponseError):
            parser.parse("{invalid json content", SIMPLE_SCHEMA)

    def test_empty_schema_skips_validation(self) -> None:
        """空 Schema 跳过验证。"""
        parser = StructuredOutputParser()
        result = parser.parse('{"anything": "goes"}', {})
        assert result["anything"] == "goes"

    def test_nested_json(self) -> None:
        """嵌套 JSON 结构。"""
        parser = StructuredOutputParser()
        schema = {
            "type": "object",
            "properties": {
                "dimensions": {
                    "type": "object",
                    "properties": {
                        "clarity": {"type": "number"},
                        "depth": {"type": "number"},
                    },
                },
            },
        }
        raw = '{"dimensions": {"clarity": 8.0, "depth": 7.5}}'
        result = parser.parse(raw, schema)
        assert result["dimensions"]["clarity"] == 8.0
        assert result["dimensions"]["depth"] == 7.5

    def test_max_retries_attribute(self) -> None:
        """max_retries 属性。"""
        parser = StructuredOutputParser(max_retries=5)
        assert parser.max_retries == 5

    def test_json_with_surrounding_text(self) -> None:
        """JSON 前后有额外文本。"""
        parser = StructuredOutputParser()
        raw = 'The evaluation result is as follows:\n{"score": 6.0, "reason": "OK"}\nEnd of evaluation.'
        result = parser.parse(raw, SIMPLE_SCHEMA)
        assert result["score"] == 6.0
