"""评估器注册中心 + BaseEvaluator 测试。"""

import pytest

from agent_eval.core.exceptions import EvaluatorNotFoundError
from agent_eval.core.types import ConstraintTier, EvalMethod
from agent_eval.evaluation.base import BaseEvaluator
from agent_eval.evaluation.registry import EvaluatorRegistry, registry


class TestEvaluatorRegistry:
    def test_register_and_create(self) -> None:
        reg = EvaluatorRegistry()

        @reg.register("test.dummy")
        class DummyEvaluator(BaseEvaluator):
            evaluator_id = "test.dummy"
            name = "Dummy"
            tier = ConstraintTier.SOFT
            method = EvalMethod.RULE

            def evaluate(self, sample, context):
                from agent_eval.core.types import EvalStatus
                return self._make_result(status=EvalStatus.PASS, score=1.0, reason="ok")

        ev = reg.create("test.dummy")
        assert ev.evaluator_id == "test.dummy"
        result = ev.evaluate(None, {})
        assert result.score == 1.0

    def test_create_with_params(self) -> None:
        reg = EvaluatorRegistry()

        @reg.register("test.with_params")
        class ParamEvaluator(BaseEvaluator):
            evaluator_id = "test.with_params"
            name = "Params"
            tier = ConstraintTier.SOFT
            method = EvalMethod.RULE

            def evaluate(self, sample, context):
                return self._make_result(
                    status=EvalStatus.PASS, score=1.0, reason=str(self.params)
                )

        ev = reg.create("test.with_params", {"key": "value"})
        assert ev.params == {"key": "value"}

    def test_not_found_error(self) -> None:
        reg = EvaluatorRegistry()
        with pytest.raises(EvaluatorNotFoundError) as exc_info:
            reg.create("nonexistent")
        assert "nonexistent" in str(exc_info.value)

    def test_duplicate_registration(self) -> None:
        reg = EvaluatorRegistry()

        @reg.register("test.dup")
        class Dup1(BaseEvaluator):
            evaluator_id = "test.dup"
            name = "Dup1"
            def evaluate(self, sample, context):
                pass

        with pytest.raises(ValueError, match="冲突"):
            @reg.register("test.dup")
            class Dup2(BaseEvaluator):
                evaluator_id = "test.dup"
                name = "Dup2"
                def evaluate(self, sample, context):
                    pass

    def test_is_registered(self) -> None:
        reg = EvaluatorRegistry()
        assert not reg.is_registered("nope")

    def test_list_registered(self) -> None:
        ids = registry.list_registered()
        assert "format.response_format" in ids
        assert "commonsense.info_accuracy" in ids


class TestGlobalRegistry:
    """验证全局 registry 中所有评估器已注册。"""

    def test_format_evaluators_registered(self) -> None:
        for eid in [
            "format.response_format",
            "format.document_count",
            "format.structure_compliance",
            "format.html_validity",
        ]:
            assert registry.is_registered(eid), f"{eid} 未注册"

    def test_commonsense_evaluators_registered(self) -> None:
        for eid in [
            "commonsense.info_accuracy",
            "commonsense.chronological_order",
            "commonsense.logical_consistency",
            "commonsense.math_formula",
            "commonsense.unit_consistency",
        ]:
            assert registry.is_registered(eid), f"{eid} 未注册"

    def test_all_can_be_created(self) -> None:
        for eid in registry.list_registered():
            ev = registry.create(eid)
            assert isinstance(ev, BaseEvaluator)
