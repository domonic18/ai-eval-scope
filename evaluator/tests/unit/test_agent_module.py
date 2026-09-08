"""Agent 模块导入冒烟与 BudgetController 行为测试。"""

import pytest


def test_import_execution_agent() -> None:
    from agent_eval.agent.executor.agent import AgentSession, ExecutionAgent

    assert ExecutionAgent is not None
    assert AgentSession is not None


def test_import_sut_tools() -> None:
    from agent_eval.agent.executor.sut_tools import SUTToolServer

    server = SUTToolServer()
    assert len(server.get_tool_names()) == 7
    assert "write_package" in server.describe_tools()


def test_import_hooks() -> None:
    from agent_eval.agent.core.budget import BudgetController

    ctrl = BudgetController(max_budget_usd=1.0)
    assert ctrl.check() == "ok"


def test_import_model_bridge_and_callbacks_and_session() -> None:
    from agent_eval.agent.core.callbacks import BudgetGuard, SessionLogCallback
    from agent_eval.agent.core.model_bridge import build_chat_model
    from agent_eval.agent.core.session import AgentSession, WorkspaceCheckpointer

    assert build_chat_model is not None
    assert BudgetGuard is not None
    assert SessionLogCallback is not None
    assert AgentSession is not None
    assert WorkspaceCheckpointer is not None


def test_agent_config_model_agnostic_fields() -> None:
    """v4.6：llm_role + 可选 model（模型无关），无 permission_mode/allowed_tools。"""
    from agent_eval.execution.models import AgentConfig

    config = AgentConfig()
    assert config.llm_role == "agent"  # LLM②：角色注册表，默认 agent（回退 text）
    assert config.model is None
    assert not hasattr(config, "permission_mode")
    assert not hasattr(config, "allowed_tools")


def test_budget_controller_states() -> None:
    from agent_eval.agent.core.budget import BudgetController

    ctrl = BudgetController(max_budget_usd=1.0, warn_threshold=0.8)
    assert ctrl.check() == "ok"
    ctrl.spent_usd = 0.85
    assert ctrl.check() == "warning"
    ctrl.spent_usd = 1.5
    assert ctrl.check() == "exceeded"


def test_budget_controller_record_accumulates() -> None:
    from agent_eval.agent.core.budget import BudgetController

    ctrl = BudgetController(max_budget_usd=1.0)
    assert ctrl.record(cost_usd=0.5, tokens=100) == "ok"
    assert ctrl.record(cost_usd=0.35, tokens=50) == "warning"  # 0.85 ≥ 80%
    assert ctrl.record(cost_usd=0.2, tokens=10) == "exceeded"
    assert ctrl.spent_usd == pytest.approx(1.05)
    assert ctrl.total_tokens == 160
