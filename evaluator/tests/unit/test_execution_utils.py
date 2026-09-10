"""execution.utils 测试——extract_by_path 路径语法（response_mapping/token_path/output_paths 共用）。"""

from __future__ import annotations

import pytest

from agent_eval.core.exceptions import ToolExecutionError
from agent_eval.execution.utils import extract_by_path

DATA = {
    "data": {"messages": [{"role": "user", "content": "q"}, {"role": "assistant", "content": "a"}]}
}


def test_plain_dotted_path() -> None:
    assert extract_by_path(DATA, "data.messages.0.role") == "user"


def test_negative_index_dotted() -> None:
    assert extract_by_path(DATA, "data.messages.-1.content") == "a"


def test_negative_index_bracket_form() -> None:
    """方括号形式（LLM 自然写法）与点分等价——jxb 事故实证的解析缺口。"""
    assert extract_by_path(DATA, "data.messages[-1].content") == "a"
    assert extract_by_path(DATA, "data.messages[0].content") == "q"


def test_negative_index_out_of_range_raises() -> None:
    """负越界此前漏成裸 IndexError——现显式报错。"""
    with pytest.raises(ToolExecutionError, match="越界"):
        extract_by_path(DATA, "data.messages.-5.content")


def test_positive_index_out_of_range_raises() -> None:
    with pytest.raises(ToolExecutionError, match="越界"):
        extract_by_path(DATA, "data.messages.9")


def test_missing_key_raises() -> None:
    with pytest.raises(ToolExecutionError, match="不存在"):
        extract_by_path(DATA, "data.nope")


def test_non_subscriptable_node_raises() -> None:
    with pytest.raises(ToolExecutionError, match="节点类型"):
        extract_by_path(DATA, "data.messages.0.content.x")
