"""chat 场景评估器测试（answer_exact 两阶段 / answer_quality / answer_consistency / 三件套注册）。"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from agent_eval.core.types import EvalStatus
from agent_eval.evaluation.evaluators.scenario.chat import (
    ChatAnswerConsistencyEvaluator,
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


class _FakeJudgeOrchestrator:
    """模拟 judge_orchestrator：templates.get/render + pool.get 直调路径。"""

    def __init__(self, extracted: str | None) -> None:
        self._extracted = extracted
        self.templates = SimpleNamespace(
            get=lambda *a, **kw: SimpleNamespace(
                system_prompt="sys", user_prompt_template="{{ content }}"
            ),
            render=lambda tpl, vars: ("sys", vars.get("content", "")),
        )
        self.pool = SimpleNamespace(
            get=lambda name=None: SimpleNamespace(
                chat=lambda msgs: SimpleNamespace(content=json.dumps({"answer": self._extracted}))
            )
        )


# ── answer_exact：两阶段（LLM 提取 → 规则比对）──


def test_answer_exact_llm_extract_mismatch_fails(tmp_path) -> None:
    """Phase 1 LLM 提取 2.8 → Phase 2 expected=3 → FAIL（reason 报提取值）。"""
    text = """$$10x = 28$$
x = 2.8 是方程的解。
若共花 **46 元**：得 **x = 3 本**（验算 ✓）
"""
    sample = _sample_with_answer(tmp_path, text)
    ev = _exact_evaluator()
    context = {
        "task_expected": {"answer": 3},
        "task_input": {"instruction": "求笔记本数"},
        "judge_orchestrator": _FakeJudgeOrchestrator("2.8"),
    }
    result = ev.evaluate(sample, context)
    assert result.status == EvalStatus.FAIL
    assert "2.8" in result.reason


def test_answer_exact_llm_extract_match_passes(tmp_path) -> None:
    """Phase 1 LLM 提取 3 → Phase 2 expected=3 → PASS。"""
    sample = _sample_with_answer(tmp_path, "答案是 3 本")
    ev = _exact_evaluator()
    context = {
        "task_expected": {"answer": 3},
        "task_input": {"instruction": "求笔记本数"},
        "judge_orchestrator": _FakeJudgeOrchestrator("3"),
    }
    result = ev.evaluate(sample, context)
    assert result.status == EvalStatus.PASS


def test_answer_exact_llm_extract_null_fails(tmp_path) -> None:
    """Phase 1 LLM 判定无明确答案 → FAIL（reason 报「未给出明确答案」）。"""
    sample = _sample_with_answer(tmp_path, "这个嘛……不太好说")
    ev = _exact_evaluator()
    context = {
        "task_expected": {"answer": 42},
        "task_input": {"instruction": "求值"},
        "judge_orchestrator": _FakeJudgeOrchestrator(None),
    }
    result = ev.evaluate(sample, context)
    assert result.status == EvalStatus.FAIL
    assert "未给出明确答案" in result.reason


def test_answer_exact_offline_fallback_fulltext(tmp_path) -> None:
    """无 judge_orchestrator → 回退全文搜索（离线退化，文档声明的局限）。"""
    sample = _sample_with_answer(tmp_path, "标准形式是 ax + b = 0（a≠0）。")
    ev = _exact_evaluator()
    result = ev.evaluate(sample, {"task_expected": {"answer": "ax + b = 0"}})
    assert result.status == EvalStatus.PASS
    assert "全文搜索" in result.reason


def test_answer_exact_offline_numeric_word_boundary(tmp_path) -> None:
    """离线退化时词边界仍生效：13/30 不命中 expected=3。"""
    sample = _sample_with_answer(tmp_path, "他买了 13 本，花费 30 元。")
    ev = _exact_evaluator()
    result = ev.evaluate(sample, {"task_expected": {"answer": 3}})
    assert result.status == EvalStatus.FAIL


def test_answer_exact_skips_when_answer_undeclared(tmp_path) -> None:
    sample = _sample_with_answer(tmp_path, "任何回答")
    result = _exact_evaluator().evaluate(sample, {"task_expected": {}})
    assert result.status == EvalStatus.SKIP


def test_answer_exact_fails_when_no_output(tmp_path) -> None:
    result = _exact_evaluator().evaluate(tmp_path, {"task_expected": {"answer": 3}})
    assert result.status == EvalStatus.FAIL


# ── answer_quality：变量注入 ──


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


# ── answer_consistency：SKIP 语义 + 变量注入 ──


def test_answer_consistency_skips_when_reference_undeclared(tmp_path) -> None:
    ev = ChatAnswerConsistencyEvaluator()
    ev.setup({})
    sample = _sample_with_answer(tmp_path, "任何回答")
    result = ev.evaluate(sample, {"task_expected": {}})
    assert result.status == EvalStatus.SKIP
    assert "expected.reference" in result.reason


def test_answer_consistency_variables_inject_reference_and_instruction() -> None:
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


# ── 三件套注册（提取模板 / 规则 / 评估器）──


def test_extract_prompt_template_registered() -> None:
    """chat_answer_extract 模板可从包内加载；规则声明正确。"""
    import yaml

    from agent_eval.evaluation.evaluators.scenario import chat as chat_mod
    from agent_eval.llm.judge.file_prompt_store import FilePromptStore
    from agent_eval.packages.manager import PackageManager

    assert "chat.answer_exact" in chat_mod.register()

    pkg = PackageManager().resolve_ref("chat")
    store = FilePromptStore(pkg.prompts_dir)
    store.load_all()
    template = store.get("chat", "chat_answer_extract")
    assert template is not None
    assert "instruction" in template.user_prompt_template

    rules = yaml.safe_load((pkg.rules_dir / "chat-quality.yaml").read_text(encoding="utf-8"))
    exact = [r for r in rules["rules"] if r["id"] == "ANS_EXACT"]
    assert len(exact) == 1
    assert exact[0]["evaluator"] == "chat.answer_exact"
