"""逐维度可解释性详情（dim_details）透传契约（docs/arch/14 §五）。

- _extract_dim_detail：从 LLM 维度对象提取 {reason, issues, highlights}（纯数值 → {}）
- JudgeRecord.dim_details：默认空、to_dict 序列化、from_dict 往返
"""

from __future__ import annotations

from agent_eval.llm.judge.orchestrator import _extract_dim_detail
from agent_eval.llm.models import JudgeRecord


def test_extract_dim_detail_from_object():
    obj = {
        "score": 9,
        "reason": "结构完整",
        "issues": [{"desc": "x", "severity": "low"}],
        "highlights": ["好"],
    }
    assert _extract_dim_detail(obj) == {
        "reason": "结构完整",
        "issues": [{"desc": "x", "severity": "low"}],
        "highlights": ["好"],
    }


def test_extract_dim_detail_partial_keys():
    # 仅 reason，无 issues/highlights
    assert _extract_dim_detail({"score": 7, "reason": "r"}) == {"reason": "r"}


def test_extract_dim_detail_non_object_returns_empty():
    # 纯数值提示词（旧/非结构化）→ 无可解释性字段
    assert _extract_dim_detail(8) == {}
    assert _extract_dim_detail("8") == {}
    assert _extract_dim_detail(None) == {}


def _bare_record(**kw):
    base = dict(
        judge_id="j1",
        constraint_id="c1",
        sample_id="s1",
        provider_name="p",
        model="m",
        template_id="t",
    )
    base.update(kw)
    return JudgeRecord(**base)


def test_record_dim_details_default_empty_and_serialized():
    r = _bare_record()
    assert r.dim_details == {}
    d = r.to_dict()
    assert d["dim_details"] == {}


def test_record_dim_details_roundtrip():
    details = {"structure": {"reason": "r", "issues": [], "highlights": ["h"]}}
    r = _bare_record(dim_details=details)
    assert r.dim_details == details
    # to_dict 含 dim_details；from_dict 能还原
    restored = JudgeRecord.from_dict(r.to_dict())
    assert restored.dim_details == details
