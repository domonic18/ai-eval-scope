"""_coerce_score 严格解析契约（orchestrator.py）。

合法形态提取分数；非法形态抛 LLMError，不再静默回退 0.0 / 正则提取字符串。
"""

from __future__ import annotations

import pytest

from agent_eval.core.exceptions import LLMError
from agent_eval.llm.judge.orchestrator import _coerce_score


@pytest.mark.parametrize("value,expected", [(8, 8.0), (8.5, 8.5), (0, 0.0), (10, 10.0)])
def test_coerce_number(value, expected):
    assert _coerce_score(value) == expected


def test_coerce_structured_object():
    # 新结构化提示词：{"score": <number>, reason, issues, highlights}
    assert _coerce_score({"score": 9, "reason": "r", "issues": [], "highlights": []}) == 9.0


@pytest.mark.parametrize(
    "bad",
    [True, False, "8", "9 分", None, [8], {"issues": []}, {}],
)
def test_coerce_illegal_raises(bad):
    # bool / str / None / list / 对象缺 score / 空对象 —— 均抛错，不静默兜底
    with pytest.raises(LLMError):
        _coerce_score(bad)
