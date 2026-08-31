"""LangGraph 回调单元测试（BudgetGuard / SessionLogCallback，arch/03 §7a.6）。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from agent_eval.agent.callbacks import BudgetGuard, SessionLogCallback
from agent_eval.agent.hooks import SessionLogger
from agent_eval.core.exceptions import BudgetExceededError


def _ai_message(input_tokens: int, output_tokens: int) -> SimpleNamespace:
    return SimpleNamespace(
        message=SimpleNamespace(
            usage_metadata={"input_tokens": input_tokens, "output_tokens": output_tokens}
        )
    )


def _result_with_generations(input_tokens: int, output_tokens: int) -> SimpleNamespace:
    return SimpleNamespace(generations=[[_ai_message(input_tokens, output_tokens)]])


def test_budget_guard_accumulates_tokens_without_pricing() -> None:
    guard = BudgetGuard(max_budget_usd=1.0)
    guard.on_llm_end(_result_with_generations(100, 50))
    guard.on_llm_end(_result_with_generations(200, 50))
    assert guard.total_tokens == 400
    assert guard.spent_usd == 0.0  # 未配置 pricing → 成本记 0


def test_budget_guard_exceeded_with_pricing() -> None:
    guard = BudgetGuard(max_budget_usd=0.01, pricing={"input_per_1k": 5.0, "output_per_1k": 10.0})
    # 2000 input × $5/1k = $10 > $0.01
    with pytest.raises(BudgetExceededError):
        guard.on_llm_end(_result_with_generations(2000, 0))


def test_budget_guard_legacy_token_usage() -> None:
    guard = BudgetGuard(max_budget_usd=1.0)
    legacy = SimpleNamespace(
        llm_output={"token_usage": {"prompt_tokens": 10, "completion_tokens": 5}}
    )
    guard.on_llm_end(legacy)
    assert guard.total_tokens == 15


def test_budget_guard_dict_response() -> None:
    guard = BudgetGuard(max_budget_usd=1.0)
    guard.on_llm_end({"usage_metadata": {"input_tokens": 7, "output_tokens": 3}})
    assert guard.total_tokens == 10


def test_session_log_callback_pairs_tool_events(tmp_path) -> None:
    logger = SessionLogger("run_1", "task_1", log_dir=tmp_path)
    callback = SessionLogCallback(logger)
    logger.log_start()

    callback.on_tool_start(
        {"name": "invoke_http_sut"}, '{"url": "x"}', run_id="r1", inputs={"url": "x"}
    )
    callback.on_tool_end('{"status_code": 200}', run_id="r1")

    events = [e.event for e in logger.events]
    assert events == ["agent_start", "tool_call", "tool_result"]
    result_event = logger.events[-1]
    assert result_event.tool_name == "invoke_http_sut"
    assert result_event.tool_status == "success"
    assert result_event.tool_call_id == logger.events[-2].tool_call_id
    assert result_event.tool_duration_ms is not None


def test_session_log_callback_tool_error(tmp_path) -> None:
    logger = SessionLogger("run_1", "task_1", log_dir=tmp_path)
    callback = SessionLogCallback(logger)
    callback.on_tool_start({"name": "read_file"}, "", run_id="r9", inputs={"file_path": "/x"})
    callback.on_tool_error(ValueError("boom"), run_id="r9")
    assert logger.events[-1].tool_status == "error"
    assert "boom" in str(logger.events[-1].tool_output_summary)
