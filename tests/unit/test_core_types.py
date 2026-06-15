"""核心类型（枚举）和异常的单元测试。"""

from agent_eval.core.exceptions import (
    AgentError,
    AgentEvalError,
    AgentTimeoutError,
    BudgetExceededError,
    CollectionError,
    ConfigError,
    ConfigFileNotFoundError,
    EvaluatorNotFoundError,
    ExecutionError,
    PackageNotFoundError,
    SchemaValidationError,
    WorkspaceError,
)
from agent_eval.core.types import (
    CascadeStageID,
    ConstraintTier,
    EvalMethod,
    EvalMode,
    EvalStatus,
    PackageStatus,
    RunMode,
    ShortCircuitPolicy,
)

# ─── 枚举测试 ───


class TestEnums:
    """枚举值正确性测试。"""

    def test_run_mode_values(self) -> None:
        assert RunMode.RUN_ONLY == "run-only"
        assert RunMode.EVAL_ONLY == "eval-only"
        assert RunMode.PIPELINE == "pipeline"

    def test_eval_mode_values(self) -> None:
        assert EvalMode.PIPELINE == "pipeline"
        assert EvalMode.AGENT == "agent"

    def test_eval_status_values(self) -> None:
        assert EvalStatus.PASS == "pass"
        assert EvalStatus.FAIL == "fail"
        assert EvalStatus.SKIP == "skip"
        assert EvalStatus.ERROR == "error"

    def test_constraint_tier_values(self) -> None:
        assert ConstraintTier.HARD_GATE == "hard_gate"
        assert ConstraintTier.HARD_SCORE == "hard_score"
        assert ConstraintTier.SOFT == "soft"
        assert ConstraintTier.PREFERENCE == "preference"

    def test_eval_method_values(self) -> None:
        assert EvalMethod.RULE == "rule"
        assert EvalMethod.FACT_VERIFY == "fact_verify"
        assert EvalMethod.MATH_VERIFY == "math_verify"
        assert EvalMethod.LLM_JUDGE == "llm_judge"
        assert EvalMethod.VISION == "vision"

    def test_cascade_stage_id(self) -> None:
        assert CascadeStageID.FORMAT_GATE == "format_gate"
        assert CascadeStageID.COMMONSENSE_GATE == "commonsense_gate"
        assert CascadeStageID.QUALITY_EVAL == "quality_eval"

    def test_short_circuit_policy(self) -> None:
        assert ShortCircuitPolicy.FAIL_FAST == "fail_fast"
        assert ShortCircuitPolicy.CONTINUE_ALL == "continue_all"

    def test_package_status(self) -> None:
        assert PackageStatus.SUCCESS == "success"
        assert PackageStatus.PARTIAL == "partial"
        assert PackageStatus.FAILED == "failed"

    def test_enum_from_string(self) -> None:
        assert RunMode("pipeline") is RunMode.PIPELINE
        assert EvalStatus("pass") is EvalStatus.PASS
        assert ConstraintTier("soft") is ConstraintTier.SOFT


# ─── 异常测试 ───


class TestExceptions:
    """异常类体系测试。"""

    def test_base_error(self) -> None:
        err = AgentEvalError("test error")
        assert str(err) == "test error"
        assert err.message == "test error"
        assert err.details == {}

    def test_base_error_with_details(self) -> None:
        err = AgentEvalError("test", details={"key": "value"})
        assert "key" in str(err) and "value" in str(err)
        assert err.details == {"key": "value"}

    def test_config_error_inherits(self) -> None:
        err = ConfigError("config broken")
        assert isinstance(err, AgentEvalError)
        assert err.message == "config broken"

    def test_schema_validation_error(self) -> None:
        errors = [{"message": "missing field", "path": "rules"}]
        err = SchemaValidationError("validation failed", errors=errors)
        assert isinstance(err, ConfigError)
        assert err.validation_errors == errors
        assert "validation failed" in str(err)

    def test_config_file_not_found(self) -> None:
        err = ConfigFileNotFoundError("/tmp/missing.yaml")
        assert isinstance(err, ConfigError)
        assert err.path == "/tmp/missing.yaml"
        assert "/tmp/missing.yaml" in str(err)

    def test_execution_error_hierarchy(self) -> None:
        assert issubclass(AgentError, ExecutionError)
        assert issubclass(ExecutionError, AgentEvalError)
        assert issubclass(AgentTimeoutError, AgentError)
        assert issubclass(BudgetExceededError, AgentError)
        assert issubclass(CollectionError, ExecutionError)

    def test_evaluator_not_found(self) -> None:
        available = ["fmt_001", "fmt_002"]
        err = EvaluatorNotFoundError("missing_eval", available=available)
        assert isinstance(err, AgentEvalError)
        assert err.evaluator_id == "missing_eval"
        assert err.available == available
        assert "missing_eval" in str(err)
        assert "fmt_001" in str(err)

    def test_package_not_found(self) -> None:
        err = PackageNotFoundError("/tmp/pkg")
        assert err.path == "/tmp/pkg"

    def test_workspace_error(self) -> None:
        err = WorkspaceError("ws error")
        assert isinstance(err, AgentEvalError)
