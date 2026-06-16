"""TaskSetBuilder — 基于模板批量生成任务集。

支持从 YAML 模板 + 变量列表通过笛卡尔积展开生成多个 Task，
最终输出符合 JSON Schema 的 task_set.yaml。
"""

from __future__ import annotations

from itertools import product
from pathlib import Path
from typing import Any

import yaml
from jinja2 import Template as JinjaTemplate

from agent_eval.config.loader import ConfigLoader
from agent_eval.execution.models import Task, TaskSet


class TaskSetBuilder:
    """从模板批量生成 TaskSet。"""

    def __init__(self, template_path: Path | str) -> None:
        """初始化 Builder 并加载模板 YAML。

        Args:
            template_path: task_set 模板文件路径。模板中包含基础 metadata
                和至少一个 task 模板；task 中可使用 Jinja2 变量占位符。
        """
        self.template_path = Path(template_path)
        self._template_data = ConfigLoader.load_yaml(self.template_path)

    def build(
        self,
        variables: dict[str, list[Any]] | None = None,
        *,
        output_path: Path | str | None = None,
    ) -> TaskSet:
        """根据变量列表展开模板，生成 TaskSet。

        Args:
            variables: 变量名到取值列表的映射。若提供多个变量，则对取值列表
                做笛卡尔积展开，为每个组合生成一组 tasks。
            output_path: 可选的输出文件路径；若提供则将生成的 task_set.yaml 写入磁盘。

        Returns:
            生成的 TaskSet 实例（已通过 Pydantic 校验）。
        """
        variables = variables or {}
        base_tasks = self._template_data.get("tasks", [])

        tasks: list[Task] = []
        if variables:
            var_names = list(variables.keys())
            var_values = [variables[name] for name in var_names]
            for combo in product(*var_values):
                combo_dict = dict(zip(var_names, combo, strict=False))
                for base_task in base_tasks:
                    rendered = self._render_task(base_task, combo_dict)
                    tasks.append(Task.model_validate(rendered))
        else:
            for base_task in base_tasks:
                tasks.append(Task.model_validate(base_task))

        task_set_data: dict[str, Any] = {
            "id": self._template_data.get("id", "generated_task_set"),
            "name": self._template_data.get("name", "Generated Task Set"),
            "description": self._template_data.get("description", ""),
            "tasks": [t.model_dump() for t in tasks],
        }

        task_set = TaskSet.model_validate(task_set_data)

        if output_path is not None:
            out = Path(output_path)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(
                yaml.safe_dump(task_set_data, sort_keys=False, allow_unicode=True),
                encoding="utf-8",
            )

        return task_set

    @staticmethod
    def _render_task(task_template: dict[str, Any], variables: dict[str, Any]) -> dict[str, Any]:
        """使用 Jinja2 对单个 task 模板做变量替换。

        先将 task 模板序列化为 YAML 字符串，渲染后再反序列化，
        从而支持任意嵌套字段中的变量替换。
        """
        raw = yaml.safe_dump(task_template, allow_unicode=True)
        rendered = JinjaTemplate(raw).render(**variables)
        return yaml.safe_load(rendered)
