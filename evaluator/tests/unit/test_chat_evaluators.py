"""chat 场景评估器测试（answer_exact 精确匹配 / answer_quality 变量注入 / answer.md 物化）。"""

from __future__ import annotations

from pathlib import Path

from agent_eval.core.types import EvalStatus
from agent_eval.evaluation.evaluators.scenario.chat import (
    ChatAnswerExactEvaluator,
    ChatAnswerQualityEvaluator,
)


def _sample_with_answer(tmp_path: Path, text: str) -> Path:
    output = tmp_path / "output"
    output.mkdir()
    (output / "answer.md").write_text(text, encoding="utf-8")
    return tmp_path


def _exact_evaluator() -> ChatAnswerExactEvaluator:
    ev = ChatAnswerExactEvaluator()
    ev.setup({})
    return ev


def test_answer_exact_numeric_word_boundary_hit(tmp_path) -> None:
    sample = _sample_with_answer(tmp_path, "解方程得 x = 3，即小明买了 3 本笔记本。")
    result = _exact_evaluator().evaluate(sample, {"task_expected": {"answer": 3}})
    assert result.status == EvalStatus.PASS and result.score == 1.0


def test_answer_exact_numeric_word_boundary_miss(tmp_path) -> None:
    """13/30 不得命中 expected=3（词边界）。"""
    sample = _sample_with_answer(tmp_path, "他买了 13 本，花费 30 元。")
    result = _exact_evaluator().evaluate(sample, {"task_expected": {"answer": 3}})
    assert result.status == EvalStatus.FAIL and result.score == 0.0


def test_answer_exact_string_substring(tmp_path) -> None:
    sample = _sample_with_answer(tmp_path, "标准形式是 ax + b = 0（a≠0）。")
    result = _exact_evaluator().evaluate(sample, {"task_expected": {"answer": "ax + b = 0"}})
    assert result.status == EvalStatus.PASS


def test_answer_exact_skips_when_answer_undeclared(tmp_path) -> None:
    sample = _sample_with_answer(tmp_path, "任何回答")
    result = _exact_evaluator().evaluate(sample, {"task_expected": {}})
    assert result.status == EvalStatus.SKIP


def test_answer_exact_fails_when_no_output(tmp_path) -> None:
    result = _exact_evaluator().evaluate(tmp_path, {"task_expected": {"answer": 3}})
    assert result.status == EvalStatus.FAIL


def test_answer_quality_variables_inject_instruction_and_must_mention() -> None:
    ev = ChatAnswerQualityEvaluator()
    ev.setup({})
    variables = ev._build_variables(
        "回答正文",
        {
            "task_input": {"instruction": "请解释一元一次方程"},
            "task_expected": {"must_mention": ["标准形式", "例题"]},
        },
    )
    assert variables["content"] == "回答正文"
    assert variables["instruction"] == "请解释一元一次方程"
    assert variables["must_mention"] == "- 标准形式\n- 例题"


def test_answer_quality_variables_default_when_no_expected() -> None:
    ev = ChatAnswerQualityEvaluator()
    ev.setup({})
    variables = ev._build_variables("t", {"task_input": {}})
    assert variables["must_mention"] == "无"
    assert variables["instruction"] == "未提供任务指令"
