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


EVENTS = {
    "events": [
        {"type": "message_start", "message_id": "m1"},
        {"type": "thought", "content": "分析中"},
        {"type": "content", "message_id": "m1", "content": "回答正文"},
        {"type": "message_end", "message_id": "m1"},
    ]
}


def test_filter_segment_takes_last_match() -> None:
    """过滤段 [k=v] 后接负下标——答案帧位置不定（thought 帧数可变）时的提取形态。"""
    assert extract_by_path(EVENTS, "events[type=content].-1.content") == "回答正文"


def test_filter_segment_on_role() -> None:
    """jxb history 类形态：按 role 过滤取末条助手消息（messages.-1 是用户消息）。"""
    assert extract_by_path(DATA, "data.messages[role=assistant].-1.content") == "a"


def test_filter_no_match_raises() -> None:
    """过滤未命中 fail-loud——不静默兜底（假成功教训）。"""
    with pytest.raises(ToolExecutionError, match="未命中"):
        extract_by_path(EVENTS, "events[type=answer].-1.content")


def test_filter_on_non_list_raises() -> None:
    with pytest.raises(ToolExecutionError, match="须为列表"):
        extract_by_path(DATA, "data[role=assistant].content")


def test_filter_keeps_existing_syntax_unchanged() -> None:
    """过滤段与既有下标/键段可自由组合，存量写法不受影响。"""
    assert extract_by_path(EVENTS, "events.0.type") == "message_start"
    assert extract_by_path(EVENTS, "events[-1].message_id") == "m1"
