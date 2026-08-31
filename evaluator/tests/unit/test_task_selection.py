"""select_tasks 测试 — glob / 逗号 / 范围 / 排除（pytest 风格任务选择）。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from agent_eval.core.exceptions import ScenarioPackageValidationError
from agent_eval.packages.assets import select_tasks


def _tasks(*ids: str) -> list[SimpleNamespace]:
    return [SimpleNamespace(id=i) for i in ids]


TASKS = _tasks(
    "identity_001",
    "knowledge_002",
    "reasoning_003",
    "creative_004",
    "memory_005",
    "instruction_006",
    "summary_007",
    "safety_violence_008",
    "safety_porn_009",
    "safety_discrimination_010",
    "safety_illegal_011",
    "bias_gender_012",
    "bias_region_013",
    "bias_culture_014",
    "bias_age_015",
)


class TestSelectAll:
    def test_none_returns_all(self) -> None:
        assert select_tasks(TASKS, None) == TASKS

    def test_star_returns_all(self) -> None:
        assert select_tasks(TASKS, "*") == TASKS

    def test_empty_string_returns_all(self) -> None:
        assert select_tasks(TASKS, "") == TASKS


class TestExactAndComma:
    def test_single_exact(self) -> None:
        result = select_tasks(TASKS, "identity_001")
        assert len(result) == 1
        assert result[0].id == "identity_001"

    def test_comma_separated(self) -> None:
        result = select_tasks(TASKS, "identity_001,safety_violence_008,bias_gender_012")
        assert [t.id for t in result] == ["identity_001", "safety_violence_008", "bias_gender_012"]

    def test_comma_deduplicates(self) -> None:
        result = select_tasks(TASKS, "identity_001,identity_001")
        assert len(result) == 1


class TestGlob:
    def test_prefix_glob(self) -> None:
        result = select_tasks(TASKS, "safety_*")
        ids = [t.id for t in result]
        assert len(ids) == 4
        assert all(i.startswith("safety_") for i in ids)

    def test_bias_glob(self) -> None:
        result = select_tasks(TASKS, "bias_*")
        assert len(result) == 4

    def test_question_mark_glob(self) -> None:
        result = select_tasks(TASKS, "*_00?")
        assert len(result) == 9  # 001-009（_00 后跟一位数字）


class TestRange:
    def test_numeric_range_dash(self) -> None:
        result = select_tasks(TASKS, "3-6")
        assert [t.id for t in result] == [
            "reasoning_003",
            "creative_004",
            "memory_005",
            "instruction_006",
        ]

    def test_numeric_range_colon(self) -> None:
        result = select_tasks(TASKS, "3:6")
        assert len(result) == 4

    def test_numeric_range_reversed(self) -> None:
        result = select_tasks(TASKS, "6-3")
        assert len(result) == 4

    def test_id_range(self) -> None:
        result = select_tasks(TASKS, "reasoning_003:summary_007")
        assert [t.id for t in result] == [
            "reasoning_003",
            "creative_004",
            "memory_005",
            "instruction_006",
            "summary_007",
        ]


class TestExclude:
    def test_star_with_exclude(self) -> None:
        result = select_tasks(TASKS, "*,!safety_porn_009")
        ids = [t.id for t in result]
        assert len(ids) == 14
        assert "safety_porn_009" not in ids

    def test_glob_with_exclude(self) -> None:
        result = select_tasks(TASKS, "safety_*,!safety_porn_009")
        ids = [t.id for t in result]
        assert len(ids) == 3
        assert "safety_porn_009" not in ids

    def test_range_with_exclude(self) -> None:
        result = select_tasks(TASKS, "1-5,!reasoning_003")
        assert len(result) == 4


class TestErrors:
    def test_no_match_raises(self) -> None:
        with pytest.raises(ScenarioPackageValidationError, match="未命中"):
            select_tasks(TASKS, "nonexistent_999")

    def test_all_excluded_raises(self) -> None:
        with pytest.raises(ScenarioPackageValidationError, match="无剩余"):
            select_tasks(TASKS, "identity_001,!identity_001")
