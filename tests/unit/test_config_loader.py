"""ConfigLoader 和 JSON Schema 校验测试。"""

from pathlib import Path

import pytest

from agent_eval.config.loader import ConfigLoader, get_schema_path
from agent_eval.core.exceptions import (
    ConfigFileNotFoundError,
    SchemaValidationError,
)

FIXTURES = Path(__file__).parent.parent / "fixtures"
CONFIGS = FIXTURES / "configs"
SCHEMAS = Path(__file__).parent.parent.parent / "assets" / "schemas"


class TestLoadYaml:
    def test_load_valid_yaml(self) -> None:
        data = ConfigLoader.load_yaml(CONFIGS / "rule_set.yaml")
        assert "version" in data
        assert "rules" in data

    def test_load_file_not_found(self) -> None:
        with pytest.raises(ConfigFileNotFoundError):
            ConfigLoader.load_yaml("/tmp/nonexistent_config.yaml")

    def test_load_task_set(self) -> None:
        data = ConfigLoader.load_yaml(CONFIGS / "task_set.yaml")
        assert "tasks" in data
        assert len(data["tasks"]) >= 1


class TestValidateSchema:
    def test_valid_rule_set_schema(self) -> None:
        data = ConfigLoader.load_yaml(CONFIGS / "rule_set.yaml")
        errors = ConfigLoader.validate_schema(data, SCHEMAS / "rule_set_schema.json")
        assert errors == []

    def test_invalid_rule_set_schema(self) -> None:
        data = ConfigLoader.load_yaml(CONFIGS / "invalid_rule_set.yaml")
        errors = ConfigLoader.validate_schema(data, SCHEMAS / "rule_set_schema.json")
        assert len(errors) > 0
        # 应该报告缺少 rules 字段
        assert any("rules" in e.get("message", "") for e in errors)

    def test_valid_task_set_schema(self) -> None:
        data = ConfigLoader.load_yaml(CONFIGS / "task_set.yaml")
        errors = ConfigLoader.validate_schema(data, SCHEMAS / "task_set_schema.json")
        assert errors == []

    def test_schema_file_not_found(self) -> None:
        with pytest.raises(ConfigFileNotFoundError):
            ConfigLoader.validate_schema({}, "/tmp/nonexistent_schema.json")


class TestLoadAndValidate:
    def test_valid_with_schema(self) -> None:
        data = ConfigLoader.load_and_validate(
            CONFIGS / "rule_set.yaml",
            SCHEMAS / "rule_set_schema.json",
        )
        assert "version" in data

    def test_invalid_raises(self) -> None:
        with pytest.raises(SchemaValidationError) as exc_info:
            ConfigLoader.load_and_validate(
                CONFIGS / "invalid_rule_set.yaml",
                SCHEMAS / "rule_set_schema.json",
            )
        assert len(exc_info.value.validation_errors) > 0

    def test_skip_schema_when_none(self) -> None:
        data = ConfigLoader.load_and_validate(CONFIGS / "rule_set.yaml")
        assert "version" in data


class TestLoadRuleSet:
    def test_load_rule_set_model(self) -> None:
        rs = ConfigLoader.load_rule_set(CONFIGS / "rule_set.yaml")
        assert rs.version == "1.0"
        assert len(rs.rules) == 2
        assert rs.rules[0].evaluator == "format.response_format"

    def test_load_rule_set_dimensions(self) -> None:
        rs = ConfigLoader.load_rule_set(CONFIGS / "rule_set.yaml")
        assert len(rs.dimensions) == 2
        assert rs.dimensions[0].id == "functional"


class TestLoadTaskSet:
    def test_load_task_set_model(self) -> None:
        ts = ConfigLoader.load_task_set(CONFIGS / "task_set.yaml")
        assert ts.id == "test_task_set"
        assert len(ts.tasks) == 2
        assert ts.tasks[1].input_mode == "directory"


class TestGetSchemaPath:
    def test_schema_path(self) -> None:
        p = get_schema_path("rule_set_schema.json")
        assert p.name == "rule_set_schema.json"
        assert "schemas" in str(p)
