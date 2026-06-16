"""RuleSDK 测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_eval.rules.models import RuleSet
from agent_eval.sdk.rules import RuleSDK


def test_sdk_create_rule_set() -> None:
    """SDK 可编程式创建 RuleSet。"""
    rs = RuleSDK.create(
        version="1.0.0",
        description="SDK 创建的规则集",
        dimensions=[{"id": "functional", "name": "功能性"}],
        cascade=[{"stage": "format", "name": "格式门控"}],
        rules=[
            {
                "id": "FMT_001",
                "name": "输出格式有效",
                "dimension": "functional",
                "stage": "format",
                "evaluator": "format.response_format",
            }
        ],
    )

    assert isinstance(rs, RuleSet)
    assert rs.version == "1.0.0"
    assert len(rs.rules) == 1


def test_sdk_add_rule(tmp_path: Path) -> None:
    """SDK 可向 RuleSet 添加规则。"""
    _ = tmp_path / "rule_set.yaml"
    rs = RuleSDK.create(
        version="1.0.0",
        dimensions=[{"id": "functional", "name": "功能性"}],
        cascade=[{"stage": "format", "name": "格式门控"}],
    )

    RuleSDK.add_rule(
        rs,
        {
            "id": "FMT_001",
            "name": "输出格式有效",
            "dimension": "functional",
            "stage": "format",
            "evaluator": "format.response_format",
        },
    )

    assert len(rs.rules) == 1
    assert rs.rules[0].id == "FMT_001"


def test_sdk_validate_detects_missing_dimension(tmp_path: Path) -> None:
    """SDK 校验能发现维度未定义。"""
    sdk = RuleSDK(tmp_path / "rule_set.yaml")
    rs = RuleSDK.create(
        version="1.0.0",
        rules=[
            {
                "id": "FMT_001",
                "name": "输出格式有效",
                "dimension": "not_exist",
                "stage": "format",
                "evaluator": "format.response_format",
            }
        ],
    )

    errors = sdk.validate(rs)
    assert any("dimension" in e for e in errors)


def test_sdk_commit_and_load(tmp_path: Path) -> None:
    """SDK 可提交并重新加载 RuleSet。"""
    sdk = RuleSDK(tmp_path / "rule_set.yaml")
    rs = RuleSDK.create(
        version="1.0.0",
        description="测试",
        dimensions=[{"id": "functional", "name": "功能性"}],
        cascade=[{"stage": "format", "name": "格式门控"}],
        rules=[
            {
                "id": "FMT_001",
                "name": "输出格式有效",
                "dimension": "functional",
                "stage": "format",
                "evaluator": "format.response_format",
            }
        ],
    )

    version = sdk.commit(rs, message="初始提交")
    assert version == "1.0.0"

    loaded = sdk.load(resolve_templates=False)
    assert loaded.version == "1.0.0"
    assert loaded.rules[0].id == "FMT_001"


def test_sdk_commit_rejects_invalid_rule_set(tmp_path: Path) -> None:
    """提交前校验失败会抛异常。"""
    sdk = RuleSDK(tmp_path / "rule_set.yaml")
    rs = RuleSDK.create(rules=[{"id": "BAD", "evaluator": "not.exist"}])

    with pytest.raises(ValueError, match="语义校验失败"):
        sdk.commit(rs)


def test_sdk_resolve_templates() -> None:
    """SDK 可解析模板引用。"""
    rs = RuleSDK.create(
        version="1.0.0",
        dimensions=[{"id": "functional", "name": "功能性"}],
        cascade=[{"stage": "format", "name": "格式门控"}],
        templates=[
            {
                "id": "fmt_template",
                "name": "格式模板",
                "dimension": "functional",
                "stage": "format",
                "evaluator": "format.response_format",
                "params": {"allowed_formats": ["md"]},
            }
        ],
        rules=[
            {
                "id": "FMT_001",
                "template_ref": "fmt_template",
                "overrides": {"params": {"allowed_formats": ["md", "html"]}},
            }
        ],
    )

    resolved = RuleSDK.resolve_templates(rs)
    rule = resolved.get_rule("FMT_001")
    assert rule is not None
    assert rule.evaluator == "format.response_format"
    assert rule.params["allowed_formats"] == ["md", "html"]
