"""ScoreAggregator 单元测试 — reward 归一化（docs/arch/07）。

核心保证：reward ∈ [0,1]、无负值（旧 format_fail=-3 已消除）；format 失败由 DR + fail-fast 体现。
"""

from __future__ import annotations

from agent_eval.core.types import ConstraintTier, EvalStatus
from agent_eval.evaluation.aggregator import ScoreAggregator
from agent_eval.evaluation.models import ConstraintResult, SampleResult, StageResult


def _stage(
    stage_id: str, status: EvalStatus, constraints: list[ConstraintResult] | None = None
) -> StageResult:
    return StageResult(stage_id=stage_id, status=status, constraint_results=constraints or [])


def _cr(cid: str, score: float, tier: ConstraintTier = ConstraintTier.SOFT) -> ConstraintResult:
    return ConstraintResult(
        constraint_id=cid, name=cid, tier=tier, status=EvalStatus.PASS, score=score
    )


def _full_quality() -> list[ConstraintResult]:
    return [
        _cr("soft.teaching_logic", 1.0, ConstraintTier.SOFT),
        _cr("soft.content_diversity", 1.0, ConstraintTier.SOFT),
        _cr("pref.style_preference", 1.0, ConstraintTier.PREFERENCE),
        _cr("pref.depth_preference", 1.0, ConstraintTier.PREFERENCE),
        _cr("pref.request_fulfillment", 1.0, ConstraintTier.PREFERENCE),
    ]


def test_reward_full_pass_is_one() -> None:
    """全维度满分 → reward = 1.0（归一化上限）。"""
    agg = ScoreAggregator()
    r = SampleResult(
        sample_id="s1",
        status=EvalStatus.PASS,
        stage_results={
            "format": _stage("format", EvalStatus.PASS),
            "commonsense": _stage("commonsense", EvalStatus.PASS),
            "quality": _stage("quality", EvalStatus.PASS, _full_quality()),
        },
    )
    score = agg.aggregate(r)
    assert score.s_format == 1.0
    assert score.s_common == 1.0
    assert score.s_soft == 1.0
    assert score.s_pref == 1.0
    assert score.reward == 1.0


def test_reward_format_fail_is_zero_not_negative() -> None:
    """format 失败（fail-fast）→ reward = 0，且 s_format = 0（不再是 -3）。"""
    agg = ScoreAggregator()
    r = SampleResult(
        sample_id="s2",
        status=EvalStatus.FAIL,
        stage_results={"format": _stage("format", EvalStatus.FAIL)},
    )
    score = agg.aggregate(r)
    assert score.s_format == 0.0  # format_fail=0，旧 -3 已消除
    assert score.reward == 0.0  # 最低分，非负


def test_reward_never_negative() -> None:
    """关键回归：reward 归一化后绝不为负（任何场景）。"""
    agg = ScoreAggregator()
    cases = [
        {"format": _stage("format", EvalStatus.FAIL)},
        {
            "format": _stage("format", EvalStatus.PASS),
            "commonsense": _stage("commonsense", EvalStatus.FAIL),
        },
        {
            "format": _stage("format", EvalStatus.PASS),
            "commonsense": _stage("commonsense", EvalStatus.PASS),
            "quality": _stage("quality", EvalStatus.PASS, [_cr("soft.teaching_logic", 0.0)]),
        },
    ]
    for stages in cases:
        r = SampleResult(sample_id="s", status=EvalStatus.PASS, stage_results=stages)
        score = agg.aggregate(r)
        assert 0.0 <= score.reward <= 1.0, f"reward 越界: {score.reward}"


def test_reward_partial_in_range() -> None:
    """部分得分 → reward 严格落在 (0,1)。"""
    agg = ScoreAggregator()
    r = SampleResult(
        sample_id="s4",
        status=EvalStatus.PASS,
        stage_results={
            "format": _stage("format", EvalStatus.PASS),
            "commonsense": _stage("commonsense", EvalStatus.PASS),
            "quality": _stage(
                "quality",
                EvalStatus.PASS,
                [
                    _cr("soft.teaching_logic", 0.5, ConstraintTier.SOFT),
                    _cr("soft.content_diversity", 0.5, ConstraintTier.SOFT),
                    _cr("pref.style_preference", 0.5, ConstraintTier.PREFERENCE),
                    _cr("pref.depth_preference", 0.5, ConstraintTier.PREFERENCE),
                    _cr("pref.request_fulfillment", 0.5, ConstraintTier.PREFERENCE),
                ],
            ),
        },
    )
    score = agg.aggregate(r)
    # (1 + 1 + 1*0.5 + 1*0.5) / 4 = 0.75
    assert score.reward == 0.75
