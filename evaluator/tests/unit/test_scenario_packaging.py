"""Phase 0 场景包标识字段测试。

验证 RuleSet/Rule/RuleTemplate、TaskSet/Task、JudgeTemplate 新增的
scenario_id/package_id（提示词额外含 namespace）字段，以及内置 courseware
资产标记与 dataset_schema.json（对齐 13 配置管理设计、06 §2.2.5）。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from jsonschema import ValidationError
from jsonschema import validate as jsonschema_validate

import agent_eval.config  # noqa: F401  触发正常初始化顺序，规避潜在 circular import
from agent_eval.config.paths import paths
from agent_eval.execution.models import Task, TaskSet
from agent_eval.llm.judge.template_manager import TemplateManager
from agent_eval.rules.models import Rule, RuleSet, RuleTemplate

# ── 规则侧：RuleSet/Rule/RuleTemplate ──────────────────────────────────────────


def test_rule_set_loads_scenario_via_alias() -> None:
    rs = RuleSet.model_validate(
        {
            "version": "1.0",
            "scenario": "courseware",
            "package_id": "courseware-quality",
            "rules": [],
        }
    )
    assert rs.scenario_id == "courseware"
    assert rs.package_id == "courseware-quality"


def test_rule_set_scenario_round_trips_by_alias() -> None:
    rs = RuleSet(scenario_id="courseware", rules=[])
    dumped = rs.model_dump(by_alias=True, exclude_none=True)
    assert dumped["scenario"] == "courseware"
    assert "scenario_id" not in dumped  # 序列化用 alias，不泄露内部字段名


def test_rule_set_accepts_field_name_too() -> None:
    # populate_by_name=True：构造时允许直接用字段名
    rs = RuleSet(scenario_id="travel-itinerary", rules=[])
    assert rs.scenario_id == "travel-itinerary"


def test_rule_and_template_carry_optional_package_fields() -> None:
    rule = Rule(id="FMT_001", scenario_id="courseware", package_id="courseware-quality")
    assert rule.scenario_id == "courseware" and rule.package_id == "courseware-quality"

    tpl = RuleTemplate(
        id="TPL_1",
        name="t",
        dimension="functional",
        stage="format",
        evaluator="format.response_format",
        scenario_id="courseware",
    )
    assert tpl.scenario_id == "courseware"


def test_rule_set_scenario_defaults_none_for_legacy_assets() -> None:
    # 未标记 scenario 的旧资产仍可加载，字段为 None（向后不破坏）
    rs = RuleSet.model_validate({"version": "1.0", "rules": [{"id": "FMT_001"}]})
    assert rs.scenario_id is None
    assert rs.package_id is None


# ── 任务侧：TaskSet/Task ───────────────────────────────────────────────────────


def test_task_set_loads_scenario_via_alias() -> None:
    ts = TaskSet.model_validate(
        {
            "id": "ts1",
            "scenario": "courseware",
            "package_id": "courseware-quality",
            "name": "n",
            "tasks": [],
        }
    )
    assert ts.scenario_id == "courseware" and ts.package_id == "courseware-quality"


def test_task_set_round_trips_by_alias() -> None:
    ts = TaskSet(id="ts1", scenario_id="courseware", name="n", tasks=[])
    assert ts.model_dump(by_alias=True, exclude_none=True)["scenario"] == "courseware"


def test_task_carries_optional_package_fields() -> None:
    task = Task(id="t1", input={}, scenario_id="courseware", package_id="courseware-quality")
    assert task.scenario_id == "courseware" and task.package_id == "courseware-quality"


# ── 提示词侧：JudgeTemplate ────────────────────────────────────────────────────


def test_judge_template_loads_scenario_namespace_package(tmp_path: Path) -> None:
    src = (
        "template_id: pedagogical_logic\n"
        "scenario: courseware\n"
        "package_id: courseware-quality\n"
        "namespace: courseware\n"
        "name: 教学逻辑评估\n"
        "system_prompt: s\n"
        "user_prompt_template: '{{ x }}'\n"
    )
    (tmp_path / "t.yaml").write_text(src, encoding="utf-8")

    mgr = TemplateManager(tmp_path)
    mgr.load_all()
    tpl = mgr.get("pedagogical_logic")
    assert tpl.scenario_id == "courseware"
    assert tpl.package_id == "courseware-quality"
    assert tpl.namespace == "courseware"


# ── dataset_schema.json ────────────────────────────────────────────────────────


def _dataset_schema() -> dict:
    return json.loads((paths.schemas_dir / "dataset_schema.json").read_text(encoding="utf-8"))


def test_dataset_schema_accepts_minimal_test_sample() -> None:
    jsonschema_validate(instance={"id": "x", "role": "test"}, schema=_dataset_schema())


def test_dataset_schema_accepts_full_test_and_reference_samples() -> None:
    schema = _dataset_schema()
    jsonschema_validate(
        instance={
            "id": "gsm8k",
            "scenario": "math",
            "role": "test",
            "backend": {
                "type": "huggingface",
                "config": {"path": "opencompass/gsm8k", "split": "test"},
            },
            "reader_cfg": {"input_columns": ["input"], "output_column": "answer"},
        },
        schema=schema,
    )
    jsonschema_validate(
        instance={
            "id": "math_reference",
            "scenario": "courseware",
            "role": "reference",
            "backend": {
                "type": "yaml_file",
                "config": {
                    "defaults_path": "datasets/_defaults.yaml",
                    "subject_files": ["datasets/math.yaml"],
                },
            },
        },
        schema=schema,
    )


def test_dataset_schema_rejects_invalid_role() -> None:
    with pytest.raises(ValidationError):
        jsonschema_validate(instance={"id": "x", "role": "invalid"}, schema=_dataset_schema())


# ── 内置 courseware 包资产标记（Phase 2 重组后位于 packages/courseware/<ver>/）──


@pytest.mark.parametrize(
    "name",
    ["coursework-quality.yaml", "coursework-gate.yaml", "coursework-vision.yaml"],
)
def test_builtin_rule_sets_marked_courseware(name: str) -> None:
    data = yaml.safe_load((paths.rules_dir / name).read_text(encoding="utf-8"))
    assert data.get("scenario") == "courseware", name


def test_builtin_prompts_and_reference_marked_courseware() -> None:
    # prompts_dir 与 knowledge_dir（参考知识，原 knowledge/）现归入内置 courseware 包
    for d in (paths.prompts_dir, paths.knowledge_dir):
        files = list(d.glob("*.yaml"))
        assert files, f"{d} 下无 yaml，可能重组后路径未对齐"  # 防止空 glob 静默通过
        for path in files:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            assert data.get("scenario") == "courseware", path


def test_builtin_rule_set_loads_with_scenario_and_passes_schema() -> None:
    from agent_eval.config.loader import ConfigLoader

    rs = ConfigLoader.load_rule_set(
        paths.rules_dir / "coursework-quality.yaml",
        schema_path=paths.schemas_dir / "rule_set_schema.json",
    )
    assert rs.scenario_id == "courseware"
