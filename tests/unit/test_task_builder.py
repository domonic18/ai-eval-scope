"""TaskSetBuilder 测试。"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from agent_eval.execution.models import TaskSet
from agent_eval.execution.task_builder import TaskSetBuilder


def _write_template(path: Path) -> None:
    data = {
        "id": "math_tasks",
        "name": "数学课件任务集",
        "tasks": [
            {
                "id": "math_{{ grade }}_{{ topic }}",
                "input": {
                    "title": "{{ topic }}课件",
                    "subject": "数学",
                    "grade": "{{ grade }}",
                },
                "constraints": {"min_documents": 1},
            }
        ],
    }
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


@pytest.fixture
def template_path(tmp_path: Path) -> Path:
    path = tmp_path / "task_set_template.yaml"
    _write_template(path)
    return path


class TestTaskSetBuilder:
    def test_build_without_variables(self, template_path: Path) -> None:
        """无变量时直接返回模板中的任务。"""
        builder = TaskSetBuilder(template_path)
        task_set = builder.build()

        assert isinstance(task_set, TaskSet)
        assert task_set.id == "math_tasks"
        assert len(task_set.tasks) == 1
        assert task_set.tasks[0].id == "math_{{ grade }}_{{ topic }}"

    def test_build_with_cartesian_product(self, template_path: Path) -> None:
        """多变量做笛卡尔积展开。"""
        builder = TaskSetBuilder(template_path)
        task_set = builder.build(
            {
                "grade": ["grade_3", "grade_4"],
                "topic": ["fraction", "decimal"],
            }
        )

        assert len(task_set.tasks) == 4
        ids = {t.id for t in task_set.tasks}
        assert ids == {
            "math_grade_3_fraction",
            "math_grade_3_decimal",
            "math_grade_4_fraction",
            "math_grade_4_decimal",
        }

        # 验证变量正确替换
        task = next(t for t in task_set.tasks if t.id == "math_grade_3_fraction")
        assert task.input["grade"] == "grade_3"
        assert task.input["title"] == "fraction课件"

    def test_build_writes_output_file(self, template_path: Path, tmp_path: Path) -> None:
        """支持写入输出文件。"""
        builder = TaskSetBuilder(template_path)
        output = tmp_path / "generated.yaml"
        builder.build(
            {"grade": ["grade_5"], "topic": ["geometry"]},
            output_path=output,
        )

        assert output.exists()
        loaded = TaskSet.model_validate(yaml.safe_load(output.read_text(encoding="utf-8")))
        assert len(loaded.tasks) == 1
        assert loaded.tasks[0].id == "math_grade_5_geometry"
