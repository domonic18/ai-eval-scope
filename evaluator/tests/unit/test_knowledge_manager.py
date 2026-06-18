"""KnowledgeBaseManager 测试。"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from agent_eval.knowledge.manager import KnowledgeBaseManager


@pytest.fixture
def knowledge_dir(tmp_path: Path) -> Path:
    """构造临时知识库目录。"""
    defaults = tmp_path / "_defaults.yaml"
    defaults.write_text(
        yaml.safe_dump(
            {
                "subject": "_defaults",
                "constants": [{"name": "pi", "value": "3.14"}],
                "misconceptions": [{"pattern": "0.999≠1", "correct": "0.999...=1"}],
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )

    math = tmp_path / "math.yaml"
    math.write_text(
        yaml.safe_dump(
            {
                "subject": "math",
                "constants": [{"name": "e", "value": "2.718"}],
                "domain_facts": {"formulas": [{"name": "勾股定理"}]},
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )

    physics = tmp_path / "physics.yaml"
    physics.write_text(
        yaml.safe_dump(
            {
                "subject": "physics",
                "constants": [{"name": "g", "value": "9.8"}],
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )

    return tmp_path


class TestKnowledgeBaseManager:
    def test_load_all_subjects(self, knowledge_dir: Path) -> None:
        """不指定 subject 时加载全部学科。"""
        manager = KnowledgeBaseManager(knowledge_dir)
        kb = manager.load()

        assert len(kb["constants"]) == 3  # pi + e + g
        assert len(kb["misconceptions"]) == 1
        assert "formulas" in kb["domain_facts"]

    def test_load_specific_subject(self, knowledge_dir: Path) -> None:
        """指定 subject 时只加载对应学科和 defaults。"""
        manager = KnowledgeBaseManager(knowledge_dir)
        kb = manager.load(subjects=["math"])

        names = {c["name"] for c in kb["constants"]}
        assert names == {"pi", "e"}
        assert "g" not in names
        assert "formulas" in kb["domain_facts"]

    def test_cache_hit(self, knowledge_dir: Path) -> None:
        """缓存命中时不再读取文件。"""
        manager = KnowledgeBaseManager(knowledge_dir)
        kb1 = manager.load(subjects=["math"])
        kb2 = manager.load(subjects=["math"])
        assert kb1 is kb2

    def test_invalidate_cache(self, knowledge_dir: Path) -> None:
        """清空缓存后重新加载。"""
        manager = KnowledgeBaseManager(knowledge_dir)
        kb1 = manager.load(subjects=["math"])
        manager.invalidate_cache()
        kb2 = manager.load(subjects=["math"])
        assert kb1 is not kb2
        assert kb1["constants"] == kb2["constants"]

    def test_list_subjects(self, knowledge_dir: Path) -> None:
        """列出可用学科。"""
        manager = KnowledgeBaseManager(knowledge_dir)
        subjects = manager.list_subjects()
        assert "math" in subjects
        assert "physics" in subjects
