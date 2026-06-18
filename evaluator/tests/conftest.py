"""全局测试 fixtures — 所有测试目录共享。"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Mock langfuse 模块（避免未安装时导入报错）
sys.modules.setdefault("langfuse", MagicMock())

from agent_eval.config import LLMConfig, ProviderConfig  # noqa: E402
from agent_eval.core.types import ConstraintTier, EvalStatus  # noqa: E402
from agent_eval.evaluation.models import (  # noqa: E402
    ConstraintResult,
    MetricsReport,
    SampleResult,
    StageResult,
)

FIXTURES = Path(__file__).parent / "fixtures"


# ─── SampleResult fixtures ───


@pytest.fixture
def sample_result_pass() -> SampleResult:
    """构造一个通过所有门控的 SampleResult。"""
    cr_format = ConstraintResult(
        constraint_id="format.response_format",
        name="文件格式检查",
        tier=ConstraintTier.HARD_GATE,
        status=EvalStatus.PASS,
        score=1.0,
        reason="全部 2 个文件格式有效",
        duration_ms=10.0,
    )
    cr_common = ConstraintResult(
        constraint_id="commonsense.info_accuracy",
        name="知识准确性检查",
        tier=ConstraintTier.HARD_SCORE,
        status=EvalStatus.PASS,
        score=1.0,
        reason="知识准确性检查通过",
        duration_ms=5.0,
    )
    cr_soft = ConstraintResult(
        constraint_id="soft.teaching_logic",
        name="教学逻辑",
        tier=ConstraintTier.SOFT,
        status=EvalStatus.PASS,
        score=0.85,
        reason="教学逻辑良好",
        duration_ms=3.0,
    )
    cr_pref = ConstraintResult(
        constraint_id="pref.style_preference",
        name="风格偏好",
        tier=ConstraintTier.PREFERENCE,
        status=EvalStatus.PASS,
        score=0.70,
        reason="降级模式",
        judge_provider=None,
        judge_model=None,
        judge_record_path=None,
        duration_ms=1.0,
    )

    return SampleResult(
        sample_id="task_001",
        status=EvalStatus.PASS,
        stage_results={
            "format": StageResult(
                stage_id="format",
                status=EvalStatus.PASS,
                constraint_results=[cr_format],
                gate_passed=True,
                duration_ms=10.0,
            ),
            "commonsense": StageResult(
                stage_id="commonsense",
                status=EvalStatus.PASS,
                constraint_results=[cr_common],
                gate_passed=True,
                duration_ms=5.0,
            ),
            "quality": StageResult(
                stage_id="quality",
                status=EvalStatus.PASS,
                constraint_results=[cr_soft, cr_pref],
                gate_passed=True,
                duration_ms=4.0,
            ),
        },
        s_format=1.0,
        s_common=1.0,
        s_soft=0.85,
        s_pref=0.70,
        reward=2.55,
        total_duration_ms=19.0,
    )


@pytest.fixture
def sample_result_fail() -> SampleResult:
    """构造一个格式门控失败的 SampleResult。"""
    cr_format = ConstraintResult(
        constraint_id="format.response_format",
        name="文件格式检查",
        tier=ConstraintTier.HARD_GATE,
        status=EvalStatus.FAIL,
        score=0.0,
        reason="输出目录中无文件",
        duration_ms=5.0,
    )

    return SampleResult(
        sample_id="task_002",
        status=EvalStatus.FAIL,
        stage_results={
            "format": StageResult(
                stage_id="format",
                status=EvalStatus.FAIL,
                constraint_results=[cr_format],
                gate_passed=False,
                duration_ms=5.0,
            ),
            "commonsense": StageResult(
                stage_id="commonsense",
                status=EvalStatus.SKIP,
                gate_passed=False,
            ),
            "quality": StageResult(
                stage_id="quality",
                status=EvalStatus.SKIP,
                gate_passed=False,
            ),
        },
        s_format=-3.0,
        s_common=0.0,
        s_soft=0.0,
        s_pref=0.0,
        reward=-3.0,
        total_duration_ms=5.0,
    )


@pytest.fixture
def metrics_report() -> MetricsReport:
    """构造 MetricsReport。"""
    from agent_eval.evaluation.models import SampleScore

    return MetricsReport(
        run_id="20260609_120000",
        total_samples=2,
        dr=0.5,
        cpr=0.5,
        avg_reward=-0.225,
        cond_r=2.55,
        avg_time_ms=12.0,
        sample_scores=[
            SampleScore(
                sample_id="task_001",
                s_format=1.0,
                s_common=1.0,
                s_soft=0.85,
                s_pref=0.70,
                reward=2.55,
            ),
            SampleScore(
                sample_id="task_002",
                s_format=-3.0,
                s_common=0.0,
                s_soft=0.0,
                s_pref=0.0,
                reward=-3.0,
            ),
        ],
        failure_breakdown={"format.response_format": 1},
    )


@pytest.fixture
def llm_config() -> LLMConfig:
    """多 Provider LLM 配置（全局 fixture，供 config/llm 等测试复用）。"""
    return LLMConfig(
        default="deepseek_judge",
        providers={
            "deepseek_judge": ProviderConfig(
                provider="deepseek",
                model="deepseek-chat",
                api_key="test-key-ds",
                base_url="https://api.deepseek.com/v1",
            ),
            "openai_judge": ProviderConfig(
                provider="openai",
                model="gpt-4",
                api_key="test-key-oai",
                base_url="https://api.openai.com/v1",
            ),
        },
    )
