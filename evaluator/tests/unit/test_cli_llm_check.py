"""_check_llm_availability 预检测试。"""

from __future__ import annotations

import pytest
import typer

from agent_eval.cli._common import _check_llm_availability
from agent_eval.rules.models import Rule, RuleSet


def _make_rule_set(evaluators: list[str], *, disabled: set[int] | None = None) -> RuleSet:
    """构造含指定 evaluator 的 RuleSet。"""
    disabled = disabled or set()
    rules: list[Rule] = []
    for i, ev in enumerate(evaluators):
        prefix = ev.split(".")[0]
        method = {
            "llm": "llm",
            "vision": "llm_vision",
            "soft": "llm",
            "pref": "llm",
            "commonsense": "rule_set",
            "rule": "rule_set",
            "format": "format",
        }.get(prefix)
        kwargs: dict[str, object] = {"method": method}
        suffix = ev.split(".", 1)[1] if "." in ev else ""
        if method in ("llm", "llm_vision"):
            kwargs["prompt_id"] = suffix
        elif method == "rule_set":
            kwargs["dataset_id"] = suffix
        elif method == "format":
            kwargs["format_type"] = "extension"
            kwargs["extensions"] = ["md"]
        rules.append(Rule(id=f"R{i}", evaluator=ev, enabled=(i not in disabled), **kwargs))
    return RuleSet(rules=rules)


def test_no_llm_evaluators_no_warning(capsys: pytest.CaptureFixture[str]) -> None:
    """rule_set 无 LLM 评估器且 judge=None → 不警告不阻断。"""
    rs = _make_rule_set(["format.response_format", "commonsense.info_accuracy"])
    _check_llm_availability(rs, None, strict=False)
    assert "LLM" not in capsys.readouterr().out


def test_llm_evaluators_warn_when_no_judge(capsys: pytest.CaptureFixture[str]) -> None:
    """rule_set 含 LLM 评估器且 judge=None → 警告列出，不阻断。"""
    rs = _make_rule_set(["soft.teaching_logic", "pref.style_preference"])
    _check_llm_availability(rs, None, strict=False)
    out = capsys.readouterr().out
    assert "soft.teaching_logic" in out
    assert "pref.style_preference" in out


def test_require_llm_blocks_when_no_judge() -> None:
    """strict=True 且 judge=None → typer.Exit 阻断退出。"""
    rs = _make_rule_set(["soft.teaching_logic"])
    with pytest.raises(typer.Exit):
        _check_llm_availability(rs, None, strict=True)


def test_judge_available_no_warning(capsys: pytest.CaptureFixture[str]) -> None:
    """rule_set 含 LLM 评估器但 judge 可用 → 不警告。"""
    rs = _make_rule_set(["soft.teaching_logic"])
    _check_llm_availability(rs, object(), strict=False)
    assert "LLM" not in capsys.readouterr().out


def test_judge_available_require_llm_no_block(capsys: pytest.CaptureFixture[str]) -> None:
    """judge 可用时 require_llm 也不阻断。"""
    rs = _make_rule_set(["soft.teaching_logic"])
    _check_llm_availability(rs, object(), strict=True)
    assert "LLM" not in capsys.readouterr().out


def test_logical_consistency_is_llm_evaluator(capsys: pytest.CaptureFixture[str]) -> None:
    """commonsense.logical_consistency 视为 LLM 评估器。"""
    rs = _make_rule_set(["commonsense.logical_consistency"])
    _check_llm_availability(rs, None, strict=False)
    assert "logical_consistency" in capsys.readouterr().out


def test_disabled_rule_not_checked(capsys: pytest.CaptureFixture[str]) -> None:
    """enabled=False 的规则不纳入检查。"""
    rs = _make_rule_set(["soft.teaching_logic"], disabled={0})
    _check_llm_availability(rs, None, strict=False)
    assert "soft" not in capsys.readouterr().out
