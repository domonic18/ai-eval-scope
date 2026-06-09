"""数据模型序列化/反序列化往返测试。"""

import json
from pathlib import Path

import pytest

from agent_eval.core.types import ConstraintTier, EvalStatus
from agent_eval.evaluation.models import (
    ConstraintResult,
    MetricsReport,
    SampleResult,
    SampleScore,
    StageResult,
)
from agent_eval.execution.models import (
    AgentConfig,
    ExecutionTrace,
    ProcessMetrics,
    SUTResponse,
    SUTToolsConfig,
    Task,
    TaskSet,
)
from agent_eval.rules.models import CascadeStage, Dimension, Rule, RuleSet
from agent_eval.storage.package import (
    EvalResultManifest,
    PackageManifest,
    PackageMetadata,
    ScoreSummary,
)


# ─── 执行侧模型 ───


class TestTaskModel:
    def test_task_basic(self) -> None:
        task = Task(
            id="t001",
            input={"subject": "math", "grade": 7},
            constraints={"min_documents": 1},
        )
        assert task.id == "t001"
        assert task.input_mode == "inline"
        assert task.file_patterns == ["*.html"]

    def test_task_directory_mode(self) -> None:
        task = Task(
            id="t002",
            input={"subject": "综合"},
            input_mode="directory",
            directory_path="/tmp/output/",
        )
        assert task.input_mode == "directory"
        assert task.directory_path == "/tmp/output/"

    def test_task_invalid_input_mode(self) -> None:
        with pytest.raises(Exception):
            Task(id="t003", input={}, input_mode="invalid")

    def test_task_roundtrip(self) -> None:
        task = Task(
            id="roundtrip",
            input={"subject": "physics"},
            expected={"points": ["浮力"]},
            constraints={"min_documents": 2, "max_documents": 10},
        )
        json_str = task.model_dump_json()
        restored = Task.model_validate_json(json_str)
        assert restored.id == task.id
        assert restored.input == task.input
        assert restored.expected == task.expected
        assert restored.constraints == task.constraints


class TestTaskSetModel:
    def test_task_set_basic(self) -> None:
        ts = TaskSet(
            id="ts001",
            name="Test Set",
            tasks=[Task(id="t1", input={}), Task(id="t2", input={})],
        )
        assert len(ts.tasks) == 2

    def test_task_set_roundtrip(self) -> None:
        ts = TaskSet(
            id="ts_rt",
            name="Roundtrip Set",
            description="test",
            tasks=[
                Task(id="t1", input={"a": 1}),
                Task(id="t2", input={"b": 2}, input_mode="directory"),
            ],
        )
        json_str = ts.model_dump_json()
        restored = TaskSet.model_validate_json(json_str)
        assert len(restored.tasks) == 2
        assert restored.tasks[1].input_mode == "directory"


class TestSUTResponse:
    def test_sut_response(self) -> None:
        resp = SUTResponse(success=True, output_files=["a.md", "b.html"])
        assert resp.success is True
        assert len(resp.output_files) == 2

    def test_sut_response_roundtrip(self) -> None:
        resp = SUTResponse(
            success=False,
            error="timeout",
            metadata={"duration": 5000},
        )
        json_str = resp.model_dump_json()
        restored = SUTResponse.model_validate_json(json_str)
        assert restored.success is False
        assert restored.error == "timeout"


class TestExecutionTrace:
    def test_trace(self) -> None:
        trace = ExecutionTrace(
            request={"method": "POST"},
            response={"status": 200},
            started_at="2026-06-09T10:00:00Z",
            finished_at="2026-06-09T10:00:14Z",
        )
        assert trace.error is None


class TestProcessMetrics:
    def test_metrics(self) -> None:
        m = ProcessMetrics(total_duration_ms=12500.0, steps=4, tool_calls=2)
        assert m.total_duration_ms == 12500.0
        assert m.dead_end is False


class TestAgentConfig:
    def test_default_config(self) -> None:
        config = AgentConfig()
        assert config.max_turns == 20
        assert config.max_budget_usd == 1.0
        assert config.model == "claude-sonnet-4-20250514"
        assert config.workspace_dir == Path("./workspace")

    def test_custom_config(self) -> None:
        config = AgentConfig(max_turns=50, max_budget_usd=5.0)
        assert config.max_turns == 50
        assert config.max_budget_usd == 5.0

    def test_invalid_max_turns(self) -> None:
        with pytest.raises(Exception):
            AgentConfig(max_turns=0)

    def test_invalid_budget(self) -> None:
        with pytest.raises(Exception):
            AgentConfig(max_budget_usd=-1.0)

    def test_roundtrip(self) -> None:
        config = AgentConfig(
            max_turns=30,
            model="claude-opus",
            workspace_dir=Path("/tmp/ws"),
        )
        json_str = config.model_dump_json()
        restored = AgentConfig.model_validate_json(json_str)
        assert restored.max_turns == 30
        assert restored.model == "claude-opus"

    def test_sut_tools_config(self) -> None:
        config = AgentConfig(
            sut_tools_config=SUTToolsConfig(
                http_base_url="http://localhost:8000",
                http_timeout=60,
            ),
        )
        assert config.sut_tools_config is not None
        assert config.sut_tools_config.http_base_url == "http://localhost:8000"


# ─── 评估侧模型 ───


class TestConstraintResult:
    def test_basic(self) -> None:
        cr = ConstraintResult(
            constraint_id="format.document_count",
            name="文档数量",
            tier=ConstraintTier.HARD_GATE,
            status=EvalStatus.PASS,
            score=1.0,
        )
        assert cr.judge_provider is None
        assert cr.module_results is None

    def test_roundtrip(self) -> None:
        cr = ConstraintResult(
            constraint_id="soft.teaching_logic",
            name="教学逻辑",
            tier=ConstraintTier.SOFT,
            status=EvalStatus.PASS,
            score=0.85,
            reason="教学逻辑清晰",
            judge_provider="deepseek_judge",
            judge_model="deepseek-chat",
        )
        d = cr.to_dict()
        restored = ConstraintResult.from_dict(d)
        assert restored.constraint_id == cr.constraint_id
        assert restored.tier == ConstraintTier.SOFT
        assert restored.score == 0.85
        assert restored.judge_provider == "deepseek_judge"

    def test_with_module_results(self) -> None:
        cr = ConstraintResult(
            constraint_id="format.directory_structure",
            name="目录结构",
            tier=ConstraintTier.HARD_GATE,
            status=EvalStatus.PASS,
            score=1.0,
            module_results=[
                {"module": "M1", "file_count": 6, "passed": True},
            ],
        )
        d = cr.to_dict()
        assert "module_results" in d
        restored = ConstraintResult.from_dict(d)
        assert restored.module_results is not None
        assert len(restored.module_results) == 1


class TestStageResult:
    def test_roundtrip(self) -> None:
        sr = StageResult(
            stage_id="format",
            status=EvalStatus.PASS,
            constraint_results=[
                ConstraintResult(
                    constraint_id="fmt_001",
                    name="格式",
                    tier=ConstraintTier.HARD_GATE,
                    status=EvalStatus.PASS,
                    score=1.0,
                ),
            ],
        )
        d = sr.to_dict()
        restored = StageResult.from_dict(d)
        assert restored.stage_id == "format"
        assert len(restored.constraint_results) == 1


class TestSampleResult:
    def test_roundtrip(self) -> None:
        sr = SampleResult(
            sample_id="s001",
            status=EvalStatus.PASS,
            s_format=1.0,
            s_common=1.0,
            reward=2.43,
        )
        d = sr.to_dict()
        restored = SampleResult.from_dict(d)
        assert restored.sample_id == "s001"
        assert restored.reward == 2.43


class TestMetricsReport:
    def test_to_dict(self) -> None:
        report = MetricsReport(
            run_id="run_001",
            total_samples=10,
            dr=0.95,
            cpr=0.88,
            avg_reward=1.72,
        )
        d = report.to_dict()
        assert d["metrics"]["DR"] == 0.95
        assert d["total_samples"] == 10


# ─── 规则侧模型 ───


class TestRuleSet:
    def test_basic(self) -> None:
        rs = RuleSet(
            version="1.0",
            description="test",
            dimensions=[Dimension(id="func", name="功能")],
            cascade=[CascadeStage(stage="format_gate", stop_on_fail=True)],
            rules=[
                Rule(
                    id="FMT_001",
                    name="格式",
                    dimension="func",
                    stage="format_gate",
                    evaluator="format.response_format",
                ),
            ],
        )
        assert len(rs.rules) == 1

    def test_get_rules_by_stage(self) -> None:
        rs = RuleSet(
            version="1.0",
            rules=[
                Rule(id="R1", name="A", dimension="f", stage="s1", evaluator="e1"),
                Rule(id="R2", name="B", dimension="f", stage="s2", evaluator="e2"),
                Rule(id="R3", name="C", dimension="f", stage="s1", evaluator="e3"),
            ],
        )
        s1_rules = rs.get_rules_by_stage("s1")
        assert len(s1_rules) == 2

    def test_get_cascade_stage(self) -> None:
        rs = RuleSet(
            version="1.0",
            cascade=[CascadeStage(stage="format", stop_on_fail=True)],
        )
        cs = rs.get_cascade_stage("format")
        assert cs is not None
        assert cs.stop_on_fail is True
        assert rs.get_cascade_stage("nonexistent") is None

    def test_get_rule(self) -> None:
        rs = RuleSet(
            version="1.0",
            rules=[Rule(id="FMT_001", name="test", dimension="f", stage="s", evaluator="e")],
        )
        r = rs.get_rule("FMT_001")
        assert r is not None
        assert r.name == "test"
        assert rs.get_rule("MISSING") is None

    def test_roundtrip(self) -> None:
        rs = RuleSet(
            version="2.0",
            rules=[
                Rule(
                    id="R1", name="Rule 1", dimension="f", stage="s",
                    evaluator="e", params={"min": 1}, weight=0.5,
                ),
            ],
        )
        json_str = rs.model_dump_json()
        restored = RuleSet.model_validate_json(json_str)
        assert restored.version == "2.0"
        assert restored.rules[0].params == {"min": 1}


# ─── 数据包模型 ───


class TestPackageModels:
    def test_package_manifest(self) -> None:
        m = PackageManifest(
            package_id="pkg_001",
            created_at="2026-06-09T10:00:00Z",
            task_id="t001",
        )
        d = json.loads(m.model_dump_json())
        assert d["package_id"] == "pkg_001"

    def test_package_metadata(self) -> None:
        m = PackageMetadata(sut_name="manual", eval_system_version="0.1.0")
        assert m.sut_name == "manual"

    def test_score_summary(self) -> None:
        s = ScoreSummary(s_format=1.0, s_common=1.0, s_soft=0.78, reward=2.43)
        d = json.loads(s.model_dump_json())
        assert d["reward"] == 2.43

    def test_eval_result_manifest(self) -> None:
        m = EvalResultManifest(
            result_id="eval_001",
            package_id="pkg_001",
            rule_set_version="v1",
            evaluated_at="2026-06-09T10:01:00Z",
        )
        assert m.result_id == "eval_001"
