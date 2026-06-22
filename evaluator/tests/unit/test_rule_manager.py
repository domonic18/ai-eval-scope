"""RuleSetManager 测试。"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

# 触发评估器注册（apply 中的语义校验需要检查 evaluator 是否已注册）
import agent_eval.evaluation.evaluators  # noqa: F401
from agent_eval.rules.manager import RuleSetManager


def _write_rule_set(path: Path, version: str = "1.0.0", rules: list | None = None) -> None:
    data = {
        "version": version,
        "description": "测试规则集",
        "meta": {"version": version, "description": "测试规则集"},
        "dimensions": [{"id": "functional", "name": "功能性"}],
        "cascade": [{"stage": "format", "name": "格式门控"}],
        "rules": rules or [],
    }
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


@pytest.fixture
def manager(tmp_path: Path) -> RuleSetManager:
    rs_path = tmp_path / "rule_set.yaml"
    _write_rule_set(
        rs_path,
        rules=[
            {
                "id": "FMT_001",
                "name": "输出格式有效",
                "dimension": "functional",
                "stage": "format",
                "evaluator": "format.response_format",
                "params": {"allowed_formats": ["md", "html"]},
            }
        ],
    )
    return RuleSetManager(rs_path)


class TestBumpVersion:
    def test_bump_patch(self, manager: RuleSetManager) -> None:
        """默认递增 patch 版本。"""
        new_version = manager.bump_version("patch", "修复参数")
        assert new_version == "1.0.1"

        rs = manager.load(resolve_templates=False)
        assert rs.version == "1.0.1"
        assert rs.meta.version == "1.0.1"
        assert any("1.0.1" in c for c in rs.meta.changelog)

    def test_bump_minor(self, manager: RuleSetManager) -> None:
        """递增 minor 版本。"""
        assert manager.bump_version("minor") == "1.1.0"

    def test_bump_major(self, manager: RuleSetManager) -> None:
        """递增 major 版本。"""
        assert manager.bump_version("major") == "2.0.0"


class TestApplyAndHistory:
    def test_apply_archives_current_version(self, manager: RuleSetManager) -> None:
        """apply 会将当前版本归档。"""
        rs = manager.load(resolve_templates=False)
        rs.rules[0].params["allowed_formats"] = ["md"]
        rs.meta.version = "1.1.0"
        rs.version = "1.1.0"

        version = manager.apply(rs, commit_message="修改允许格式")
        assert version == "1.1.0"

        # 历史目录应存在归档
        archive = manager.history_dir / "rule_set_1.0.0.yaml"
        assert archive.exists()

        # 变更历史应记录
        history = manager.list_history()
        assert len(history) >= 1
        assert history[-1].change_type == "apply"

    def test_apply_validates_semantics(self, manager: RuleSetManager) -> None:
        """apply 前执行语义校验，失败时抛异常。"""
        rs = manager.load(resolve_templates=False)
        rs.rules[0].evaluator = "not.exist"

        with pytest.raises(ValueError, match="语义校验失败"):
            manager.apply(rs)


class TestDiff:
    def test_diff_detects_modifications(self, manager: RuleSetManager) -> None:
        """diff 能识别规则修改。"""
        rs = manager.load(resolve_templates=False)
        rs.rules[0].params["allowed_formats"] = ["md"]
        rs.meta.version = "1.1.0"
        rs.version = "1.1.0"
        manager.apply(rs, commit_message="修改格式")

        diff = manager.diff("1.0.0", "1.1.0")
        assert diff.version_from == "1.0.0"
        assert diff.version_to == "1.1.0"
        assert len(diff.modified_rules) == 1
        assert diff.modified_rules[0]["rule_id"] == "FMT_001"

    def test_diff_no_changes(self, manager: RuleSetManager) -> None:
        """相同版本 diff 无差异。"""
        # 先归档 1.0.0
        rs = manager.load(resolve_templates=False)
        manager.apply(rs, commit_message="归档初始版本")

        diff = manager.diff("1.0.0", "1.0.0")
        assert diff.version_from == diff.version_to
        assert not diff.added_rules
        assert not diff.removed_rules
        assert not diff.modified_rules


class TestRollback:
    def test_rollback_to_previous_version(self, manager: RuleSetManager) -> None:
        """rollback 能恢复到归档版本。"""
        rs = manager.load(resolve_templates=False)
        rs.rules[0].params["allowed_formats"] = ["md"]
        rs.meta.version = "1.1.0"
        rs.version = "1.1.0"
        manager.apply(rs, commit_message="修改格式")

        rolled = manager.rollback("1.0.0")
        assert rolled.version == "1.0.0"

        current = manager.load(resolve_templates=False)
        assert current.version == "1.0.0"
        assert current.rules[0].params["allowed_formats"] == ["md", "html"]
