"""KnowledgeMerger — 将提取/转换产物合并到 knowledge yaml。

范式参考 rules/manager.py 的 RuleSetManager（apply/归档/写盘）。
保持 KnowledgeBaseManager 纯读，Merger 独立负责写入。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from agent_eval.config.paths import paths
from agent_eval.knowledge_pipeline.models import KnowledgePatch

# 字段 → 去重键
_DEDUP_KEYS = {
    "constants": "name",
    "misconceptions": "pattern",
}


class KnowledgeMerger:
    """知识点合并器——将提取/转换产物合并到 knowledge yaml。

    Args:
        knowledge_dir: knowledge 目录路径，默认 assets/knowledge/。
    """

    def __init__(self, knowledge_dir: Path | str | None = None) -> None:
        self.knowledge_dir = (
            Path(knowledge_dir) if knowledge_dir else paths.assets_dir / "knowledge"
        )

    def _subject_path(self, subject: str) -> Path:
        """获取学科 yaml 路径。"""
        return self.knowledge_dir / f"{subject}.yaml"

    def _read_yaml(self, path: Path) -> dict[str, Any]:
        """读取 yaml（不存在返回空 dict）。"""
        if not path.exists():
            return {}
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    def merge(
        self,
        patch: KnowledgePatch,
        subject: str,
        strategy: str = "skip",
        dry_run: bool = False,
    ) -> dict[str, int]:
        """合并 patch 到 <subject>.yaml 的对应字段。

        Args:
            patch: 要合并的知识补丁。
            subject: 目标学科（如 chemistry）。
            strategy: 去重策略——"skip"（重名跳过）/ "replace"（覆盖）。
            dry_run: 只报告不写盘。

        Returns:
            {added: int, skipped: int, replaced: int, total: int}
        """
        yaml_path = self._subject_path(subject)
        data = self._read_yaml(yaml_path)

        field = patch.field
        existing: list[dict] = data.get(field, [])
        dedup_key = _DEDUP_KEYS.get(field, "name")

        # 构建现有项索引
        existing_map: dict[str, int] = {}
        for idx, item in enumerate(existing):
            key_val = str(item.get(dedup_key, ""))
            if key_val:
                existing_map[key_val] = idx

        added = 0
        skipped = 0
        replaced = 0

        for item in patch.items:
            key_val = str(item.get(dedup_key, ""))
            if key_val and key_val in existing_map:
                if strategy == "replace":
                    existing[existing_map[key_val]] = item
                    replaced += 1
                else:
                    skipped += 1
            else:
                existing.append(item)
                if key_val:
                    existing_map[key_val] = len(existing) - 1
                added += 1

        data[field] = existing

        stats = {
            "added": added,
            "skipped": skipped,
            "replaced": replaced,
            "total": len(existing),
        }

        if not dry_run:
            yaml_path.write_text(
                yaml.safe_dump(data, allow_unicode=True, sort_keys=False, default_flow_style=False),
                encoding="utf-8",
            )

        return stats

    def list_field(self, subject: str, field: str) -> list[dict[str, Any]]:
        """列出某学科某字段的现有条目。"""
        yaml_path = self._subject_path(subject)
        data = self._read_yaml(yaml_path)
        return data.get(field, [])
