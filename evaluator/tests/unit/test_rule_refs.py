"""规则集引用完整性校验（rule_refs）与引擎全失败守卫测试。

背景（2026-09-03 实测事故）：guide 示例把 method 枚举值 ``llm_judge`` 写进
``evaluator`` 字段，Agent 照抄 → 运行时 10 条规则全部「未注册的评估器」被跳过 →
0 评估器仍产出全 0 报告。修复三件：双端引用对账门禁（本文件主体）+ 引擎全失败
守卫 + guide 示例修正（meta 测试钉死 guide 不再教未注册 ID）。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest

from agent_eval.core.exceptions import EvaluationError
from agent_eval.evaluation.engine import (
    EvaluatorConfig,
    PipelineConfig,
    PipelineEngine,
    StageConfig,
)
from agent_eval.evaluation.registry import registry
from agent_eval.evaluation.rule_refs import check_rule_references

MANIFEST = "package:\n  id: demo\n  scenario: demo\n  version: 0.1.0\n"


def _seed(tmp_path: Path, files: dict[str, str]) -> Path:
    for rel, content in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    return tmp_path


def _rule_set(**rule: Any) -> str:
    base = {"id": "R1", "evaluator": "format.response_format"}
    base.update(rule)
    fields = ", ".join(f"{k}: {v}" for k, v in base.items())
    return (
        "version: '1.0'\n"
        "dimensions:\n  - {id: d1, name: 维度, weight: 1.0}\n"
        "cascade:\n  - {stage: quality, name: 质量, stop_on_fail: false}\n"
        f"rules:\n  - {{{fields}}}\n"
    )


def test_unregistered_evaluator_reported_with_guidance(tmp_path: Path) -> None:
    root = _seed(
        tmp_path,
        {"agent_eval.yaml": MANIFEST, "rules/r.yaml": _rule_set(evaluator="llm_judge")},
    )
    errors = check_rule_references(root)
    assert len(errors) == 1
    assert "R1" in errors[0] and "llm_judge" in errors[0]
    # 指引三要素：注册 ID 语义、可用清单、entry_points 通道
    assert "注册 ID" in errors[0] and "format.response_format" in errors[0]
    assert "entry_points" in errors[0]


def test_entry_points_declared_ids_are_recognized(tmp_path: Path) -> None:
    """回归：包清单已声明 chat entry_points 时 chat.* 运行时可用——不得误判未注册。"""
    manifest = (
        MANIFEST
        + '  entry_points:\n    evaluators: "agent_eval.evaluation.evaluators.scenario.chat:register"\n'
    )
    root = _seed(
        tmp_path,
        {
            "agent_eval.yaml": manifest,
            "rules/r.yaml": _rule_set(evaluator="chat.answer_quality", prompt_id="p1"),
            "prompts/p1.yaml": "template_id: p1\nsystem_prompt: x\n",
        },
    )
    assert check_rule_references(root) == []


def test_dangling_prompt_dimension_stage_reported(tmp_path: Path) -> None:
    root = _seed(
        tmp_path,
        {
            "agent_eval.yaml": MANIFEST,
            "rules/r.yaml": _rule_set(prompt_id="ghost", dimension="nope", stage="elsewhere"),
        },
    )
    errors = check_rule_references(root)
    assert any("prompt_id 'ghost'" in e for e in errors)
    assert any("dimension 'nope'" in e for e in errors)
    assert any("stage 'elsewhere'" in e for e in errors)


def test_prompt_id_resolved_from_prompts_dir(tmp_path: Path) -> None:
    root = _seed(
        tmp_path,
        {
            "agent_eval.yaml": MANIFEST,
            "rules/r.yaml": _rule_set(prompt_id="judge1", evaluator=""),
            "prompts/j.yaml": "template_id: judge1\nsystem_prompt: x\n",
        },
    )
    assert check_rule_references(root) == []


def test_judge_template_stray_variable_reported(tmp_path: Path) -> None:
    """回归（agent-security 包事故）：判官模板写评估器不注入的 {{ response }}——
    运行时 StrictUndefined 必炸且该规则 0 分，落盘前对账须打回。"""
    manifest = (
        MANIFEST
        + '  entry_points:\n    evaluators: "agent_eval.evaluation.evaluators.scenario.chat:register"\n'
    )
    root = _seed(
        tmp_path,
        {
            "agent_eval.yaml": manifest,
            "rules/r.yaml": _rule_set(evaluator="chat.answer_quality", prompt_id="p1"),
            "prompts/p1.yaml": (
                "template_id: p1\nsystem_prompt: x\n"
                'user_prompt_template: "任务：{{ instruction }}\\n回答：{{ response }}"\n'
            ),
        },
    )
    errors = check_rule_references(root)
    assert len(errors) == 1
    assert "'response'" in errors[0]
    # 打回文案带契约清单（copy, don't recall——Agent 照抄即可修复）
    assert "content" in errors[0] and "instruction" in errors[0]


def test_judge_template_contract_variables_pass(tmp_path: Path) -> None:
    """契约内变量（含 must_mention 空值兜底写法）全部通过，零误伤。"""
    manifest = (
        MANIFEST
        + '  entry_points:\n    evaluators: "agent_eval.evaluation.evaluators.scenario.chat:register"\n'
    )
    root = _seed(
        tmp_path,
        {
            "agent_eval.yaml": manifest,
            "rules/r.yaml": _rule_set(evaluator="chat.answer_quality", prompt_id="p1"),
            "prompts/p1.yaml": (
                "template_id: p1\nsystem_prompt: x\n"
                'user_prompt_template: "任务：{{ instruction }}\\n产出：{{ content }}\\n'
                '要点：{{ must_mention }}"\n'
            ),
        },
    )
    assert check_rule_references(root) == []


def test_judge_template_check_skipped_without_prompt_id_or_contract(tmp_path: Path) -> None:
    """渐进声明契约：未声明 prompt_variables 的评估器（如 format.*）不做变量对账。"""
    root = _seed(
        tmp_path,
        {
            "agent_eval.yaml": MANIFEST,
            "rules/r.yaml": _rule_set(prompt_id="p1"),
            "prompts/p1.yaml": (
                'template_id: p1\nsystem_prompt: x\nuser_prompt_template: "随意 {{ any_var }}"\n'
            ),
        },
    )
    assert check_rule_references(root) == []


def test_rule_without_prompt_id_falls_back_to_missing_default_template(tmp_path: Path) -> None:
    """规则不声明 prompt_id 时运行时回退评估器类默认 template_id——模板缺失同样
    延迟到运行时才炸（「未找到 Prompt 模板」该规则 0 分），落盘前对齐。"""
    manifest = (
        MANIFEST
        + '  entry_points:\n    evaluators: "agent_eval.evaluation.evaluators.scenario.chat:register"\n'
    )
    root = _seed(
        tmp_path,
        {
            "agent_eval.yaml": manifest,
            "rules/r.yaml": _rule_set(evaluator="chat.answer_quality", **{"id": "R1"}),
            "prompts/other.yaml": "template_id: other\nsystem_prompt: x\n",
        },
    )
    errors = check_rule_references(root)
    assert len(errors) == 1
    assert "chat_answer_quality" in errors[0] and "prompt_id" in errors[0]


def test_default_template_found_contract_still_applies(tmp_path: Path) -> None:
    """回退默认模板存在时变量契约同样对账（越界变量无处可逃）。"""
    manifest = (
        MANIFEST
        + '  entry_points:\n    evaluators: "agent_eval.evaluation.evaluators.scenario.chat:register"\n'
    )
    root = _seed(
        tmp_path,
        {
            "agent_eval.yaml": manifest,
            "rules/r.yaml": _rule_set(evaluator="chat.answer_quality"),
            "prompts/q.yaml": (
                "template_id: chat_answer_quality\nsystem_prompt: x\n"
                'user_prompt_template: "任务：{{ instruction }} 回答：{{ response }}"\n'
            ),
        },
    )
    errors = check_rule_references(root)
    assert len(errors) == 1 and "'response'" in errors[0]


def test_guide_variable_contract_table_matches_registry() -> None:
    """meta 钉死（防文档副本漂移）：guide §4 变量契约表与评估器类声明双向一致。"""
    import agent_eval.evaluation.evaluators  # noqa: F401
    import agent_eval.evaluation.evaluators.scenario.chat  # noqa: F401
    from agent_eval.config.paths import PACKAGE_ROOT
    from agent_eval.evaluation.registry import registry

    text = (PACKAGE_ROOT / "assets" / "guides" / "scenario-package-format.md").read_text(
        encoding="utf-8"
    )
    table: dict[str, set[str]] = {}
    for line in text.splitlines():
        if not line.startswith("| `"):
            continue
        cells = line.split("|")
        eid = cells[1].strip().strip("`")
        table[eid] = set(re.findall(r"\{\{\s*(\w+)\s*\}\}", cells[2]))
    assert table, "guide 应含变量契约表"
    declared = {
        eid: set(contract)
        for eid in registry.list_registered()
        if (cls := registry.class_of(eid)) is not None
        and (contract := getattr(cls, "prompt_variables", None)) is not None
    }
    for eid, vars_ in table.items():
        assert eid in declared, f"guide 契约表引用了未声明契约的评估器: {eid}"
        assert vars_ == declared[eid], f"guide 契约表 {eid} 变量漂移: {vars_} ≠ {declared[eid]}"
    missing = set(declared) - set(table)
    assert not missing, f"已声明契约的评估器未入 guide 契约表: {missing}"


def test_prompt_variables_contract_matches_build_variables() -> None:
    """meta 钉死（防双份声明漂移）：类级 prompt_variables ≡ _build_variables 实际注入键。"""
    import agent_eval.evaluation.evaluators  # noqa: F401
    import agent_eval.evaluation.evaluators.scenario.chat  # noqa: F401
    from agent_eval.evaluation.registry import registry

    for eid in registry.list_registered():
        cls = registry.class_of(eid)
        contract = getattr(cls, "prompt_variables", None) if cls else None
        if contract is None:
            continue
        injected = set(cls()._build_variables("", {}))
        assert injected == set(contract), (
            f"{eid} 的 prompt_variables {sorted(contract)} 与 _build_variables 实际注入"
            f"{sorted(injected)} 漂移——落盘对账以声明为准，声明错 = 门禁失明"
        )


def test_prompt_num_samples_validated(tmp_path: Path) -> None:
    """判官模板 num_samples 防呆：声明时必须为 ≥1 整数（0/负数/非整数运行时才炸）。"""
    from agent_eval.llm.judge.stability import StabilityController

    manifest = (
        MANIFEST
        + '  entry_points:\n    evaluators: "agent_eval.evaluation.evaluators.scenario.chat:register"\n'
    )
    root = _seed(
        tmp_path,
        {
            "agent_eval.yaml": manifest,
            "rules/r.yaml": _rule_set(evaluator="chat.answer_quality", prompt_id="p1"),
            "prompts/p1.yaml": "template_id: p1\nsystem_prompt: x\nnum_samples: 0\n",
        },
    )
    errors = check_rule_references(root)
    assert len(errors) == 1 and "num_samples" in errors[0] and "≥1" in errors[0]

    # 非整数（字符串数字）同样打回
    (tmp_path / "prompts" / "p1.yaml").write_text(
        "template_id: p1\nsystem_prompt: x\nnum_samples: '3'\n", encoding="utf-8"
    )
    assert len(check_rule_references(root)) == 1

    # 运行时尾部防线：0 采样给出语义化报错而非「no median for empty data」
    with pytest.raises(ValueError, match="num_samples"):
        StabilityController().evaluate_stable(lambda _seed: {}, [], num_samples=0)


def test_prompt_num_samples_valid_value_passes(tmp_path: Path) -> None:
    manifest = (
        MANIFEST
        + '  entry_points:\n    evaluators: "agent_eval.evaluation.evaluators.scenario.chat:register"\n'
    )
    root = _seed(
        tmp_path,
        {
            "agent_eval.yaml": manifest,
            "rules/r.yaml": _rule_set(evaluator="chat.answer_quality", prompt_id="p1"),
            "prompts/p1.yaml": (
                "template_id: p1\nsystem_prompt: x\nnum_samples: 1\n"
                'user_prompt_template: "任务：{{ instruction }} 产出：{{ content }}"\n'
            ),
        },
    )
    assert check_rule_references(root) == []


def test_disabled_rule_not_checked(tmp_path: Path) -> None:
    """enabled: false 的规则运行时被跳过——对账语义一致，不报噪音。"""
    root = _seed(
        tmp_path,
        {
            "agent_eval.yaml": MANIFEST,
            "rules/r.yaml": _rule_set(**{"enabled": "false", "evaluator": "llm_judge"}),
        },
    )
    assert check_rule_references(root) == []


def test_guide_examples_only_reference_registered_ids() -> None:
    """meta 钉死：guide 的 yaml 示例不得再教未注册 ID（本次事故的直接源头）。"""
    import agent_eval.evaluation.evaluators  # noqa: F401
    import agent_eval.evaluation.evaluators.scenario.chat  # noqa: F401
    from agent_eval.config.paths import PACKAGE_ROOT
    from agent_eval.evaluation.registry import registry

    text = (PACKAGE_ROOT / "assets" / "guides" / "scenario-package-format.md").read_text(
        encoding="utf-8"
    )
    ids = set(re.findall(r"evaluator:\s*([a-z][a-z_.]+)", text))
    assert ids, "guide 应含 evaluator 示例"
    unknown = ids - set(registry.list_registered())
    assert not unknown, f"guide 示例引用了未注册评估器: {unknown}"


# ── 引擎全失败守卫：全部评估器创建失败 → 显式中止，不产出全 0 报告 ────────────


def _config(names: list[str]) -> PipelineConfig:
    return PipelineConfig(
        stages=[
            StageConfig(
                id="quality",
                short_circuit_policy="continue_all",
                evaluators=[EvaluatorConfig(n) for n in names],
            )
        ]
    )


def test_all_evaluators_failed_aborts_before_garbage_report() -> None:
    # 全局单例注册表（与运行时同源：内置评估器已随包导入注册）
    with pytest.raises(EvaluationError, match="全部评估器创建失败") as ei:
        PipelineEngine(_config(["llm_judge", "ghost.eval"]), registry)
    assert "llm_judge" in str(ei.value) and "ghost.eval" in str(ei.value)


def test_partial_failure_keeps_skip_semantics() -> None:
    engine = PipelineEngine(_config(["format.response_format", "llm_judge"]), registry)
    assert len(engine.stages[0].evaluators) == 1


def test_empty_pipeline_no_guard() -> None:
    engine = PipelineEngine(PipelineConfig(stages=[]), registry)
    assert engine.stages == []


def test_stage_without_evaluators_is_legal_empty_pipeline() -> None:
    """直接构造「有 stage 但 0 评估器」未尝试创建——合法形态，守卫不拦（回归）。"""
    config = PipelineConfig(
        stages=[StageConfig(id="quality", short_circuit_policy="continue_all", evaluators=[])]
    )
    engine = PipelineEngine(config, registry)
    assert engine.stages[0].evaluators == []
