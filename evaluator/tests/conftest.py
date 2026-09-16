"""全局测试 fixtures — 所有测试目录共享。"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Mock 未安装的可选依赖（避免未安装时导入报错）
sys.modules.setdefault("langfuse", MagicMock())
sys.modules.setdefault("huggingface_hub", MagicMock())
for _ms_mod in ("modelscope", "modelscope.hub", "modelscope.hub.snapshot_download"):
    sys.modules.setdefault(_ms_mod, MagicMock())

from agent_eval.config import LLMConfig, ProviderConfig  # noqa: E402
from agent_eval.core.types import ConstraintTier, EvalStatus  # noqa: E402
from agent_eval.evaluation.models import (  # noqa: E402
    ConstraintResult,
    MetricsReport,
    SampleResult,
    StageResult,
)

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def _isolate_project_packages(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """项目包发现根指向空目录：PackageStore 现会扫描 cwd 一级子目录，
    开发者在 evaluator/ 下真实生成的包（如 ``weekly-report-package/``）不得漏进单测。"""
    monkeypatch.setenv("AGENT_EVAL_PROJECT_DIR", str(tmp_path / "no-project-packages"))


@pytest.fixture(autouse=True)
def _isolate_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """workspace 根指向测试临时目录：走到真实执行段的 CLI 测试（如 run --sut-name）
    曾把 pytest 运行写进 evaluator/workspace/runs/，污染用户的「查看结果」列表。"""
    monkeypatch.setenv("WORKSPACE_DIR", str(tmp_path / "workspace"))


@pytest.fixture(autouse=True)
def _isolate_sut_credentials(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """凭证密钥区指向空文件：preflight / missing_credential_fields 走无注入点的
    CredentialStore()，开发者本机已录入的真实凭证不得影响单测的缺失判定。"""
    monkeypatch.setenv("AGENT_EVAL_SUT_CREDENTIALS", str(tmp_path / "no-sut-credentials.json"))


@pytest.fixture(autouse=True)
def _reset_cli_output_format() -> None:
    """每例复位 CLI 输出形态（global rich console 挂载）：--output-format json 的
    CliRunner 用例会把全局态置 json（stdout 代理到 stderr）且 CliRunner 不还原——
    泄漏给同 worker 后续用例（test_cli_llm_check 断言 out 为空即此因，全量跑偶发）。"""
    from agent_eval.cli.console.output import set_output_format

    set_output_format("text")


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
        stage_metrics={"reward": 2.55, "soft": 0.85, "pref": 0.70},
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
        stage_metrics={"reward": 0.0},
        reward=0.0,
        total_duration_ms=5.0,
    )


@pytest.fixture
def metrics_report() -> MetricsReport:
    """构造 MetricsReport（场景化 metrics dict + metric_definitions + sample_scores dict）。"""
    return MetricsReport(
        run_id="20260609_120000",
        total_samples=2,
        metrics={
            "courseware:document_rate": 0.5,
            "courseware:constraint_pass_rate": 0.5,
            "courseware:reward": -0.225,
        },
        metric_definitions=[
            {
                "id": "courseware:document_rate",
                "name": "格式合格率",
                "threshold": 0.95,
                "unit": "ratio",
            },
            {
                "id": "courseware:constraint_pass_rate",
                "name": "内容合格率",
                "threshold": 0.9,
                "unit": "ratio",
            },
            {"id": "courseware:reward", "name": "综合得分", "threshold": 0.7, "unit": "score"},
        ],
        avg_time_ms=12.0,
        sample_scores=[
            {"sample_id": "task_001", "reward": 2.55, "soft": 0.85, "pref": 0.70},
            {"sample_id": "task_002", "reward": -3.0, "soft": 0.0, "pref": 0.0},
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


@pytest.fixture(autouse=True)
def _isolate_platform_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """平台身份密钥区指向空路径：main.py 启动会 apply_platform_env 注入
    os.environ，开发者真实 ~/.agent_eval/platform.json（若登录过）不得漏进单测。"""
    monkeypatch.setenv("AGENT_EVAL_PLATFORM_CONFIG", str(tmp_path / "no-platform.json"))
