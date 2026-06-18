"""配置加载器 — YAML 解析与 JSON Schema 校验。

支持加载 pipeline.yaml、rule_set.yaml、task_set.yaml 等配置文件，
并通过 JSON Schema 进行合法性校验。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml
from jsonschema import ValidationError
from jsonschema import validate as jsonschema_validate

from agent_eval.config.llm import LLMConfig
from agent_eval.config.paths import paths
from agent_eval.core.exceptions import (
    ConfigError,
    ConfigFileNotFoundError,
    SchemaValidationError,
)
from agent_eval.execution.models import TaskSet
from agent_eval.rules.models import RuleSet
from agent_eval.rules.template import TemplateResolver
from agent_eval.rules.validation import RuleSetValidator


class ConfigLoader:
    """配置文件加载器。

    负责读取 YAML 配置文件并执行 JSON Schema 校验。
    """

    @staticmethod
    def load_yaml(path: Path | str) -> dict[str, Any]:
        """加载 YAML 配置文件。

        Args:
            path: YAML 文件路径。

        Returns:
            解析后的字典。

        Raises:
            ConfigFileNotFoundError: 文件不存在。
            ConfigError: YAML 解析失败。
        """
        path = Path(path)
        if not path.exists():
            raise ConfigFileNotFoundError(str(path))

        try:
            content = path.read_text(encoding="utf-8")
            data = yaml.safe_load(content)
        except yaml.YAMLError as e:
            raise ConfigError(f"YAML 解析失败 ({path}): {e}") from e

        if not isinstance(data, dict):
            raise ConfigError(f"配置文件必须为 YAML 映射类型 ({path})，得到: {type(data).__name__}")

        return data

    @staticmethod
    def validate_schema(data: dict[str, Any], schema_path: Path | str) -> list[dict]:
        """使用 JSON Schema 校验配置数据。

        Args:
            data: 待校验的配置数据。
            schema_path: JSON Schema 文件路径。

        Returns:
            校验错误列表（空列表表示校验通过）。

        Raises:
            ConfigFileNotFoundError: Schema 文件不存在。
        """
        schema_path = Path(schema_path)
        if not schema_path.exists():
            raise ConfigFileNotFoundError(str(schema_path))

        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        errors: list[dict] = []

        try:
            jsonschema_validate(instance=data, schema=schema)
        except ValidationError as e:
            errors.append(
                {
                    "message": e.message,
                    "path": ".".join(str(p) for p in e.absolute_path) if e.absolute_path else "",
                    "validator": e.validator,
                    "expected": e.schema if hasattr(e, "schema") else None,
                }
            )

        return errors

    @staticmethod
    def load_and_validate(
        path: Path | str,
        schema_path: Path | str | None = None,
    ) -> dict[str, Any]:
        """加载 YAML 配置并执行 Schema 校验。

        Args:
            path: YAML 文件路径。
            schema_path: JSON Schema 文件路径（可选，不传则跳过校验）。

        Returns:
            校验通过的配置数据。

        Raises:
            ConfigFileNotFoundError: 文件不存在。
            ConfigError: YAML 解析失败。
            SchemaValidationError: Schema 校验失败。
        """
        data = ConfigLoader.load_yaml(path)

        if schema_path is not None:
            errors = ConfigLoader.validate_schema(data, schema_path)
            if errors:
                raise SchemaValidationError(
                    f"配置校验失败 ({path})",
                    errors=errors,
                )

        return data

    @staticmethod
    def load_rule_set(
        path: Path | str,
        schema_path: Path | str | None = None,
        *,
        resolve_templates: bool = True,
        validate_semantics: bool = False,
    ) -> RuleSet:
        """加载规则集配置并转换为 RuleSet 模型。

        Args:
            path: rule_set.yaml 文件路径。
            schema_path: JSON Schema 文件路径（可选）。
            resolve_templates: 是否解析 template_ref 模板引用（默认 True）。
            validate_semantics: 是否执行语义校验（默认 False，保持向后兼容）。

        Returns:
            RuleSet 实例。

        Raises:
            ConfigError: 语义校验失败时（仅当 validate_semantics=True）。
        """
        data = ConfigLoader.load_and_validate(path, schema_path)
        rule_set = RuleSet.model_validate(data)

        if resolve_templates and rule_set.templates:
            rule_set = TemplateResolver(rule_set).resolve()

        if validate_semantics:
            errors = RuleSetValidator().validate(rule_set)
            if errors:
                raise ConfigError(f"RuleSet 语义校验失败 ({path}): {errors}")

        return rule_set

    @staticmethod
    def load_task_set(
        path: Path | str,
        schema_path: Path | str | None = None,
    ) -> TaskSet:
        """加载任务集配置并转换为 TaskSet 模型。

        Args:
            path: task_set.yaml 文件路径。
            schema_path: JSON Schema 文件路径（可选）。

        Returns:
            TaskSet 实例。
        """
        data = ConfigLoader.load_and_validate(path, schema_path)
        return TaskSet.model_validate(data)

    @staticmethod
    def load_task_set_template(
        template_path: Path | str,
        variables: dict[str, list[Any]] | None = None,
        *,
        output_path: Path | str | None = None,
    ) -> TaskSet:
        """加载 task_set 模板并根据变量列表生成 TaskSet。

        Args:
            template_path: task_set 模板文件路径。
            variables: 变量名到取值列表的映射（可选）。
            output_path: 输出文件路径（可选）。

        Returns:
            生成的 TaskSet 实例。
        """
        from agent_eval.execution.task_builder import TaskSetBuilder

        builder = TaskSetBuilder(template_path)
        return builder.build(variables, output_path=output_path)

    @staticmethod
    def load_llm_config(
        path: Path | str,
        schema_path: Path | str | None = None,
    ) -> LLMConfig:
        """加载 LLM 配置并转换为 LLMConfig 模型。

        Args:
            path: llm_config.yaml 文件路径。
            schema_path: JSON Schema 文件路径（可选）。

        Returns:
            LLMConfig 实例。
        """
        data = ConfigLoader.load_and_validate(path, schema_path)
        # 兼容顶层 llm: 或直接就是 providers 结构
        llm_data = data.get("llm", data)
        return LLMConfig.model_validate(llm_data)


def get_schema_path(schema_name: str) -> Path:
    """获取 Schema 文件的标准路径。

    Args:
        schema_name: Schema 文件名（如 rule_set_schema.json）。

    Returns:
        Schema 文件的完整路径。
    """
    return paths.schemas_dir / schema_name
