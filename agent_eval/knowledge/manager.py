"""知识库管理。

统一加载、合并、缓存 `assets/knowledge/` 下的学科知识库文件，
为事实验证评估器（如 `commonsense.info_accuracy`）提供结构化知识数据。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from agent_eval.config.paths import paths


class KnowledgeBaseManager:
    """知识库加载与管理器。

    加载策略：
    - `_defaults.yaml` 始终加载，包含跨学科通用规则；
    - 按 `subjects` 列表按需加载对应学科文件；
    - `subjects=None` 时加载全部学科文件。
    """

    def __init__(self, knowledge_dir: Path | str | None = None) -> None:
        self.knowledge_dir = (
            Path(knowledge_dir) if knowledge_dir else paths.assets_dir / "knowledge"
        )
        self._defaults_path = self.knowledge_dir / "_defaults.yaml"
        self._cache: dict[str, dict[str, Any]] = {}

    def load(self, subjects: list[str] | None = None) -> dict[str, Any]:
        """加载并合并知识库。

        Args:
            subjects: 学科标识列表，如 ["math", "history"]；为 None 时加载全部。

        Returns:
            合并后的 dict，包含 constants、misconceptions、domain_facts。
        """
        cache_key = ",".join(sorted(subjects)) if subjects else "__all__"
        if cache_key in self._cache:
            return self._cache[cache_key]

        merged: dict[str, Any] = {
            "constants": [],
            "misconceptions": [],
            "domain_facts": {},
        }

        # 1. 始终加载 _defaults.yaml
        if self._defaults_path.exists():
            data = self._load_yaml(self._defaults_path)
            self._merge_section(data, merged)

        # 2. 加载学科文件（排除 _ 前缀）
        for yaml_file in sorted(self.knowledge_dir.glob("[!_]*.yaml")):
            data = self._load_yaml(yaml_file)
            if data is None:
                continue
            file_subject = data.get("subject", "")
            if subjects is None or file_subject in subjects:
                self._merge_section(data, merged)

        self._cache[cache_key] = merged
        return merged

    def list_subjects(self) -> list[str]:
        """返回可用的学科标识列表。"""
        subjects: list[str] = []
        for yaml_file in sorted(self.knowledge_dir.glob("[!_]*.yaml")):
            data = self._load_yaml(yaml_file)
            if data and "subject" in data:
                subjects.append(data["subject"])
        return subjects

    def invalidate_cache(self) -> None:
        """清空缓存。"""
        self._cache.clear()

    @staticmethod
    def _merge_section(source: dict[str, Any] | None, target: dict[str, Any]) -> None:
        """将 source 中的 constants/misconceptions/domain_facts 合并到 target。

        constants 和 misconceptions 是 list，做 extend 合并。
        domain_facts 是嵌套 dict，按子 key 递归合并。
        """
        if source is None:
            return
        for key in ("constants", "misconceptions"):
            items = source.get(key, [])
            if items:
                target.setdefault(key, []).extend(items)

        df = source.get("domain_facts")
        if df and isinstance(df, dict):
            existing = target.setdefault("domain_facts", {})
            for sub_key, sub_val in df.items():
                if isinstance(sub_val, list):
                    existing.setdefault(sub_key, []).extend(sub_val)
                elif isinstance(sub_val, dict):
                    existing.setdefault(sub_key, {}).update(sub_val)
                else:
                    existing[sub_key] = sub_val

    def _load_yaml(self, path: Path) -> dict[str, Any] | None:
        """安全加载单个 YAML 文件。"""
        try:
            with open(path, encoding="utf-8") as f:
                data = yaml.safe_load(f)
        except (OSError, yaml.YAMLError):
            return None
        return data if isinstance(data, dict) else None
