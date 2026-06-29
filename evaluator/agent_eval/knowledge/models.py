"""知识点完善管道数据模型（Pydantic v2）。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel

# ─── 评测题模型 ───


class Choice(BaseModel):
    """选择题选项。"""

    label: str
    text: str


class Answer(BaseModel):
    """正确答案。"""

    label: str
    text: str


class Question(BaseModel):
    """统一题目模型（parse_dataset 产出的 JSONL 格式的类型化版本）。"""

    id: str
    question: str
    choices: list[Choice]
    answer: Answer
    source: str
    source_subset: str | None = None

    @property
    def distractors(self) -> list[str]:
        """干扰项文本列表（排除正确答案）。"""
        return [c.text for c in self.choices if c.label != self.answer.label]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Question:
        """从 parse_dataset 产出的 JSONL dict 构造。"""
        return cls(
            id=data["id"],
            question=data["question"],
            choices=[Choice(**c) for c in data["choices"]],
            answer=Answer(**data["answer"]),
            source=data["source"],
            source_subset=data.get("source_subset"),
        )


# ─── 提取产物模型 ───


class ExtractedItem(BaseModel):
    """单条提取产物（带来源追溯）。"""

    field: str  # constants / misconceptions / domain_facts
    data: dict[str, Any]  # {name, value, ...} 或 {pattern, correct, ...}
    source: str  # 题目 id 或数据源 id


class ExtractedBatch(BaseModel):
    """一批提取产物。"""

    field: str
    items: list[ExtractedItem]
    source_dataset: str  # 数据源名（arc / cmmlu / periodic_table）
    extractor: str  # 提取器/转换器类名


# ─── 合并补丁模型 ───


class KnowledgePatch(BaseModel):
    """可合并到 knowledge yaml 的补丁。"""

    field: str  # constants / misconceptions / domain_facts
    items: list[dict[str, Any]]  # 直接的 dict（合并到 yaml 对应字段）
    source: str  # 来源标注

    @classmethod
    def from_batch(cls, batch: ExtractedBatch) -> KnowledgePatch:
        """从 ExtractedBatch 转换（提取 data 字段，保留 source 追溯）。"""
        items = []
        for item in batch.items:
            merged = dict(item.data)
            if "source" not in merged:
                merged["source"] = item.source
            items.append(merged)
        return cls(field=batch.field, items=items, source=batch.source_dataset)

    @classmethod
    def from_yaml(cls, path: Path) -> KnowledgePatch:
        """从待审核 YAML 文件加载（extract/convert 命令的输出）。

        YAML 格式：{field: [items...]}
        """
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data, dict) or len(data) != 1:
            raise ValueError(f"YAML 格式错误：期望单字段映射，得到 {type(data)}")
        field, items = next(iter(data.items()))
        if not isinstance(items, list):
            raise ValueError(f"YAML 格式错误：{field} 的值应为列表")
        return cls(field=field, items=items, source=str(path))
