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


# ── chat.answer_consistency（expected.reference 语义一致性）──


def test_answer_consistency_skips_when_reference_undeclared(tmp_path) -> None:
    """未声明 expected.reference → SKIP（不计分），与 answer_exact 的 SKIP 语义一致。"""
    from agent_eval.evaluation.evaluators.scenario.chat import ChatAnswerConsistencyEvaluator

    ev = ChatAnswerConsistencyEvaluator()
    ev.setup({})
    sample = _sample_with_answer(tmp_path, "任何回答")
    result = ev.evaluate(sample, {"task_expected": {}})
    assert result.status == EvalStatus.SKIP
    assert "expected.reference" in result.reason


def test_answer_consistency_variables_inject_reference_and_instruction() -> None:
    from agent_eval.evaluation.evaluators.scenario.chat import ChatAnswerConsistencyEvaluator

    ev = ChatAnswerConsistencyEvaluator()
    ev.setup({})
    variables = ev._build_variables(
        "我是 SasanAgent 助手",
        {
            "task_input": {"instruction": "请介绍你自己"},
            "task_expected": {"reference": "我是 SasanAgent，通用 AI 助手"},
        },
    )
    assert variables["content"] == "我是 SasanAgent 助手"
    assert variables["reference"] == "我是 SasanAgent，通用 AI 助手"
    assert variables["instruction"] == "请介绍你自己"


def test_answer_consistency_rule_and_prompt_registered(tmp_path) -> None:
    """规则集声明 ANS_CONSIST + 提示词模板可加载（模板/规则/评估器三件套齐全）。"""
    import yaml

    from agent_eval.evaluation.evaluators.scenario import chat as chat_mod
    from agent_eval.llm.judge.file_prompt_store import FilePromptStore
    from agent_eval.packages.manager import PackageManager

    assert "chat.answer_consistency" in chat_mod.register()

    pkg = PackageManager().resolve_ref("chat")
    rules = yaml.safe_load((pkg.rules_dir / "chat-quality.yaml").read_text(encoding="utf-8"))
    consist = [r for r in rules["rules"] if r["id"] == "ANS_CONSIST"]
    assert len(consist) == 1
    assert consist[0]["evaluator"] == "chat.answer_consistency"

    store = FilePromptStore(pkg.prompts_dir)
    store.load_all()
    template = store.get("chat", "chat_answer_consistency")
    assert template is not None
    assert "reference" in template.user_prompt_template  # 模板消费 reference 变量
