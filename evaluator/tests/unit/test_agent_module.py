"""Agent 模块骨架文件导入测试。"""

import pytest


def test_import_execution_agent() -> None:
    from agent_eval.agent.execution_agent import ExecutionAgent

    assert ExecutionAgent is not None


def test_import_evaluation_agent() -> None:
    from agent_eval.agent.evaluation_agent import EvaluationAgent

    assert EvaluationAgent is not None


def test_import_sut_tools() -> None:
    from agent_eval.agent.sut_tools import SUTToolServer

    server = SUTToolServer()
    assert len(server.get_tool_names()) == 7


def test_import_eval_tools() -> None:
    from agent_eval.agent.eval_tools import EvalToolServer

    assert EvalToolServer is not None


def test_import_plan_parser() -> None:
    from agent_eval.agent.plan_parser import EvalPlan, EvalPlanLoader

    assert EvalPlan is not None
    assert EvalPlanLoader is not None


def test_import_hooks() -> None:
    from agent_eval.agent.hooks import BudgetController

    ctrl = BudgetController(max_budget_usd=1.0)
    assert ctrl.check() == "ok"


def test_execution_agent_raises() -> None:
    import asyncio

    from agent_eval.agent.execution_agent import ExecutionAgent
    from agent_eval.execution.models import AgentConfig

    agent = ExecutionAgent(config=AgentConfig())
    with pytest.raises(NotImplementedError):
        asyncio.run(
            agent.run_task(
                task=type("Task", (), {"id": "t1", "input": {}})(),
            )
        )


def test_evaluation_agent_raises() -> None:
    import asyncio

    from agent_eval.agent.evaluation_agent import EvaluationAgent

    agent = EvaluationAgent()
    with pytest.raises(NotImplementedError):
        asyncio.run(agent.evaluate("/tmp", "/tmp"))


def test_plan_loader_raises() -> None:
    from agent_eval.agent.plan_parser import EvalPlanLoader

    with pytest.raises(NotImplementedError):
        EvalPlanLoader.load("/tmp/plan.md")


def test_plan_to_system_prompt() -> None:
    from agent_eval.agent.plan_parser import EvalPlan

    plan = EvalPlan(
        plan_id="test-plan",
        version="1.0",
        target="test",
        max_turns=30,
        budget_usd=1.5,
        body="# Test Plan\n\nSome content.",
    )
    prompt = plan.to_system_prompt()
    assert "test-plan" in prompt
    assert "30" in prompt
    assert "$1.50" in prompt
    assert "# Test Plan" in prompt


def test_budget_controller_warning() -> None:
    from agent_eval.agent.hooks import BudgetController

    ctrl = BudgetController(max_budget_usd=1.0, warn_threshold=0.8)
    ctrl.spent_usd = 0.85
    assert ctrl.check() == "warning"


def test_budget_controller_exceeded() -> None:
    from agent_eval.agent.hooks import BudgetController

    ctrl = BudgetController(max_budget_usd=1.0)
    ctrl.spent_usd = 1.5
    assert ctrl.check() == "exceeded"
