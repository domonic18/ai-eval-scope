"""Phase 1 场景化聚合与指标测试。

验证 ScenarioScoreAggregator / ScenarioMetricsCalculator 在 courseware 默认策略下
与旧 ScoreAggregator / MetricsCalculator 输出完全一致（等价复刻），以及安全表达式
引擎的边界行为。对齐 04 评估引擎设计 §七之二。
"""

from __future__ import annotations

import pytest

import agent_eval.config  # noqa: F401  触发正常初始化顺序，规避潜在 circular import
from agent_eval.core.exceptions import ScenarioExpressionError
from agent_eval.core.types import ConstraintTier, EvalStatus
from agent_eval.evaluation.aggregator import ScoreAggregator
from agent_eval.evaluation.metrics import MetricsCalculator
from agent_eval.evaluation.models import ConstraintResult, SampleResult, StageResult
from agent_eval.evaluation.scenario import (
    COURSEWARE_DEFAULT_METRICS,
    COURSEWARE_DEFAULT_POLICY,
    ScenarioMetricsCalculator,
    ScenarioScoreAggregator,
    safe_eval,
)
from agent_eval.evaluation.scenario.models import (
    AggregationPolicy,
    MetricDefinition,
    ScenarioConfig,
    StageWeight,
)

# ── 测试夹具：构造 SampleResult ─────────────────────────────────────────────────


def _cr(cid: str, tier: ConstraintTier, status: EvalStatus, score: float = 1.0) -> ConstraintResult:
    return ConstraintResult(constraint_id=cid, name=cid, tier=tier, status=status, score=score)


def _stage(
    sid: str, status: EvalStatus, gate: bool, results: list[ConstraintResult] | None = None
) -> StageResult:
    return StageResult(
        stage_id=sid, status=status, gate_passed=gate, constraint_results=results or []
    )


def _make(
    fmt_pass: bool,
    com_pass: bool,
    soft_t: float = 1.0,
    soft_d: float = 1.0,
    pstyle: float = 1.0,
    pdepth: float = 1.0,
    pful: float = 1.0,
    *,
    skip_after_format_fail: bool = False,
    sid: str = "s",
) -> SampleResult:
    """构造课件风格 SampleResult。

    skip_after_format_fail=True 时模拟 fail-fast：format 失败后 commonsense/quality 为 SKIP。
    """
    fst = _stage("format", EvalStatus.PASS if fmt_pass else EvalStatus.FAIL, fmt_pass)
    if skip_after_format_fail and not fmt_pass:
        cst = _stage("commonsense", EvalStatus.SKIP, False)
        qst = _stage("quality", EvalStatus.SKIP, False)
    else:
        cst = _stage("commonsense", EvalStatus.PASS if com_pass else EvalStatus.FAIL, com_pass)
        qst = _stage(
            "quality",
            EvalStatus.PASS,
            True,
            [
                _cr("soft.teaching_logic", ConstraintTier.SOFT, EvalStatus.PASS, soft_t),
                _cr("soft.content_diversity", ConstraintTier.SOFT, EvalStatus.PASS, soft_d),
                _cr("pref.style_preference", ConstraintTier.PREFERENCE, EvalStatus.PASS, pstyle),
                _cr("pref.depth_preference", ConstraintTier.PREFERENCE, EvalStatus.PASS, pdepth),
                _cr("pref.request_fulfillment", ConstraintTier.PREFERENCE, EvalStatus.PASS, pful),
            ],
        )
    sr = SampleResult(sample_id=sid, status=EvalStatus.PASS)
    sr.stage_results = {"format": fst, "commonsense": cst, "quality": qst}
    return sr


def _backfill_legacy_scores(r: SampleResult) -> None:
    """模拟 PipelineEngine：用旧 ScoreAggregator 回填 stage_metrics（+ reward）到 SampleResult。

    SampleScore 保留 s_*（旧 deprecated 聚合器输出）；新模型以 stage_metrics dict 为准，
    soft/pref/reward 从 SampleScore 映射填入。
    """
    sc = ScoreAggregator().aggregate(r)
    r.stage_metrics = {"reward": sc.reward, "soft": sc.s_soft, "pref": sc.s_pref}
    r.reward = sc.reward


# ── P1-1 模型往返 ──────────────────────────────────────────────────────────────


def test_models_round_trip() -> None:
    policy = AggregationPolicy(
        id="t",
        scenario_id="travel",
        stage_weights=[StageWeight(stage_id="safety", weight=1.0, is_gate=True)],
        normalize_to=(0.0, 1.0),
    )
    md = MetricDefinition(id="m", name="n", expression="mean(reward)", threshold=0.5, unit="ratio")
    cfg = ScenarioConfig(scenario_id="travel", aggregation_policy=policy, metric_definitions=[md])
    dumped = cfg.model_dump()
    restored = ScenarioConfig.model_validate(dumped)
    assert restored.aggregation_policy.id == "t"
    assert restored.metric_definitions[0].expression == "mean(reward)"


# ── P1-2 聚合器等价复刻 ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "fmt_pass,com_pass,scores",
    [
        (True, True, (1, 1, 1, 1, 1)),
        (True, True, (0.5, 0.5, 0.5, 0.5, 0.5)),
        (True, False, (0.0, 0.8, 0.3, 0.6, 0.9)),
        (False, True, (0.2, 0.9, 0.33, 0.66, 0.99)),
        (False, False, (0.1, 0.2, 0.3, 0.4, 0.5)),
    ],
)
def test_aggregator_equivalence(fmt_pass, com_pass, scores) -> None:
    r = _make(fmt_pass, com_pass, *scores)
    old = ScoreAggregator().aggregate(r).reward
    new = ScenarioScoreAggregator(COURSEWARE_DEFAULT_POLICY).aggregate(r)["reward"]
    assert new == pytest.approx(old, abs=1e-12)


def test_aggregator_equivalence_with_fail_fast_skip() -> None:
    """format 失败 → commonsense/quality SKIP，聚合 reward 应与旧实现一致（0.0）。"""
    r = _make(False, True, skip_after_format_fail=True)
    old = ScoreAggregator().aggregate(r).reward
    new = ScenarioScoreAggregator(COURSEWARE_DEFAULT_POLICY).aggregate(r)["reward"]
    assert new == pytest.approx(old, abs=1e-12)
    assert new == 0.0


def test_aggregator_exposes_per_stage_metrics() -> None:
    r = _make(True, True)
    out = ScenarioScoreAggregator(COURSEWARE_DEFAULT_POLICY).aggregate(r)
    assert set(["reward", "soft", "pref"]).issubset(out.keys())


# ── P1-3 指标计算等价复刻 ───────────────────────────────────────────────────────


def _batch() -> list[SampleResult]:
    results = []
    for i, (fp, cp, s) in enumerate(
        [
            (True, True, (1, 1, 1, 1, 1)),
            (True, True, (0.5, 0.5, 0.5, 0.5, 0.5)),
            (True, False, (0.0, 0.8, 0.3, 0.6, 0.9)),
            (False, True, (0.2, 0.9, 0.33, 0.66, 0.99)),
            (False, False, (0.1, 0.2, 0.3, 0.4, 0.5)),
            (True, True, (0.7, 0.4, 0.2, 0.8, 0.55)),
        ]
    ):
        r = _make(fp, cp, *s, sid=f"s{i}")
        _backfill_legacy_scores(r)
        results.append(r)
    return results


def test_metrics_equivalence() -> None:
    results = _batch()
    old = MetricsCalculator().compute(results, run_id="r")
    new = ScenarioMetricsCalculator(COURSEWARE_DEFAULT_METRICS).compute(results)
    assert new["courseware:document_rate"] == pytest.approx(
        old.metrics["courseware:document_rate"], abs=1e-12
    )
    assert new["courseware:constraint_pass_rate"] == pytest.approx(
        old.metrics["courseware:constraint_pass_rate"], abs=1e-12
    )
    assert new["courseware:reward"] == pytest.approx(old.metrics["courseware:reward"], abs=1e-12)
    assert new["courseware:soft"] == pytest.approx(old.metrics["courseware:soft"], abs=1e-12)
    assert new["courseware:pref"] == pytest.approx(old.metrics["courseware:pref"], abs=1e-12)


def test_metrics_empty_results_returns_empty() -> None:
    new = ScenarioMetricsCalculator(COURSEWARE_DEFAULT_METRICS).compute([])
    assert new == {}


# ── P1-3 安全表达式引擎 ─────────────────────────────────────────────────────────


def test_safe_eval_basic() -> None:
    assert safe_eval("mean(reward)", {"reward": [0.0, 1.0]}) == 0.5
    assert (
        safe_eval("count(format_gate) / total", {"format_gate": [True, False], "total": 2}) == 0.5
    )
    assert safe_eval(
        "gated_mean(reward, format_gate, commonsense_gate)",
        {
            "reward": [0.2, 0.4, 0.6],
            "format_gate": [True, True, False],
            "commonsense_gate": [True, False, True],
        },
    ) == pytest.approx(0.2)  # 仅第一个样本双门控通过


@pytest.mark.parametrize(
    "expr",
    [
        "__import__('os')",  # 禁止调用未注册函数 / 名称
        "open('/etc/passwd')",  # 禁止内置非白名单函数
        "(1).__class__",  # 禁止属性访问
        "reward.__class__",  # 禁止属性访问
        "globals()",  # 禁止非白名单内置
        "1; 2",  # 多语句（eval 模式应直接拒绝/不可解析）
    ],
)
def test_safe_eval_rejects_dangerous(expr: str) -> None:
    with pytest.raises(ScenarioExpressionError):
        safe_eval(expr, {"reward": [1.0]})


def test_safe_eval_unknown_variable() -> None:
    with pytest.raises(ScenarioExpressionError):
        safe_eval("mean(nonexistent)", {"reward": [1.0]})
