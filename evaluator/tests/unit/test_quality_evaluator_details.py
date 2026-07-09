"""quality_evaluators details 组装契约（docs/arch/14 §五.3）。

mock _invoke_judge 返回带 dim_details 的 record，断言 ConstraintResult.details.dimensions[]
含 band（由分派生）+ 透传 reason/issues/highlights。
"""

from __future__ import annotations

from types import SimpleNamespace

from agent_eval.evaluation.evaluators.quality_evaluators import TeachingLogicEvaluator
from agent_eval.llm.models import JudgeRecord


def _bare_record(**kw):
    base = dict(
        judge_id="j1",
        constraint_id="soft.teaching_logic",
        sample_id="s1",
        provider_name="deepseek_judge",
        model="deepseek-chat",
        template_id="pedagogical_logic",
    )
    base.update(kw)
    return JudgeRecord(**base)


def test_quality_details_dimensions_carry_issues_band_highlights(tmp_path, monkeypatch):
    # sample = Path，output/ 下放文本（供 collect_text_content 读取）
    (tmp_path / "output").mkdir()
    (tmp_path / "output" / "index.md").write_text("# 分数入门\n教学设计内容……")

    ev = TeachingLogicEvaluator()

    # mock orchestrator.templates.get → 含 dimensions 的模板
    dims = [
        SimpleNamespace(dim_id="structure", name="结构完整性", weight=0.4),
        SimpleNamespace(dim_id="progression", name="知识递进", weight=0.3),
        SimpleNamespace(dim_id="engagement", name="互动设计", weight=0.3),
    ]
    orchestrator = SimpleNamespace(
        templates={"pedagogical_logic": SimpleNamespace(dimensions=dims)}
    )

    scores = {"structure": 9.0, "progression": 8.0, "engagement": 5.0}
    dim_details = {
        "structure": {"reason": "结构完整", "issues": [], "highlights": ["导入自然"]},
        "progression": {"reason": "递进合理", "issues": [], "highlights": []},
        "engagement": {
            "reason": "互动不足",
            "issues": [{"desc": "缺少互动设计", "severity": "high", "evidence": "单向呈现"}],
            "highlights": [],
        },
    }
    record = _bare_record(
        dim_details=dim_details,
        confidence={"structure": "high", "progression": "high", "engagement": "low"},
        summary="全局评语",
    )
    monkeypatch.setattr(ev, "_invoke_judge", lambda *a, **k: (scores, record, {}))

    cr = ev.evaluate(tmp_path, {"judge_orchestrator": orchestrator, "evidence_dir": tmp_path})

    by_id = {d["id"]: d for d in cr.details["dimensions"]}
    # band 由 0-10 分派生
    assert by_id["structure"]["band"] == "优秀"  # 9.0
    assert by_id["progression"]["band"] == "良好"  # 8.0
    assert by_id["engagement"]["band"] == "合格"  # 5.0
    # 透传 reason/issues/highlights
    assert by_id["structure"]["highlights"] == ["导入自然"]
    assert by_id["engagement"]["reason"] == "互动不足"
    assert by_id["engagement"]["issues"] == [
        {"desc": "缺少互动设计", "severity": "high", "evidence": "单向呈现"}
    ]
    assert by_id["engagement"]["confidence"] == "low"
    # judge 溯源
    assert cr.judge_provider == "deepseek_judge"
    assert cr.judge_model == "deepseek-chat"
