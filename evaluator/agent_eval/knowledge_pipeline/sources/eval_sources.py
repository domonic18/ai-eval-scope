"""评测题数据源（arc parquet / cmmlu CSV → questions）。

迁移自 scripts/parse_dataset.py 的 parse_arc / parse_cmmlu。
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from agent_eval.config.paths import paths
from agent_eval.knowledge_pipeline.base import DataSource
from agent_eval.knowledge_pipeline.models import Answer, Choice, Question
from agent_eval.knowledge_pipeline.registry import register_source


@register_source("arc")
class ArcSource(DataSource):
    """AI2 ARC 数据源（parquet 格式）。

    目录结构：``{data_dir}/ARC-Challenge/*train*.parquet`` + ``ARC-Easy/*train*.parquet``
    """

    kind = "questions"

    def __init__(
        self,
        data_dir: Path | str | None = None,
        subjects: list[str] | None = None,
    ) -> None:
        self.data_dir = Path(data_dir) if data_dir else paths.default_workspace / "datasets" / "arc"
        self.subjects = subjects  # arc 无学科字段，此参数忽略

    def read(self, limit: int | None = None, **kwargs: Any) -> list[Question]:
        import pyarrow.parquet as pq

        questions: list[Question] = []
        for split_dir in sorted(self.data_dir.glob("ARC-*/")):
            for pq_file in sorted(split_dir.glob("*train*.parquet")):
                table = pq.read_table(pq_file).to_pydict()
                for i in range(len(table["id"])):
                    choices_data = table["choices"][i]
                    answer_key = table["answerKey"][i]
                    answer_text = ""
                    for lab, txt in zip(choices_data["label"], choices_data["text"]):
                        if lab == answer_key:
                            answer_text = txt
                            break
                    questions.append(
                        Question(
                            id=table["id"][i],
                            question=table["question"][i],
                            choices=[
                                Choice(label=lab, text=txt)
                                for lab, txt in zip(choices_data["label"], choices_data["text"])
                            ],
                            answer=Answer(label=answer_key, text=answer_text),
                            source="arc",
                            source_subset=split_dir.name,
                        )
                    )
                    if limit and len(questions) >= limit:
                        return questions
        return questions


@register_source("cmmlu")
class CmmluSource(DataSource):
    """CMMLU 数据源（CSV 格式，需先解压 zip 到 extracted/）。

    目录结构：``{data_dir}/extracted/test/<subject>.csv``
    CSV 格式：``,Question,A,B,C,D,Answer``
    """

    kind = "questions"

    def __init__(
        self,
        data_dir: Path | str | None = None,
        subjects: list[str] | None = None,
    ) -> None:
        self.data_dir = (
            Path(data_dir) if data_dir else paths.default_workspace / "datasets" / "cmmlu"
        )
        self.subjects = subjects

    def read(self, limit: int | None = None, **kwargs: Any) -> list[Question]:
        test_dir = self.data_dir / "extracted" / "test"
        csv_files = sorted(test_dir.glob("*.csv"))
        if self.subjects:
            csv_files = [f for f in csv_files if any(s in f.name for s in self.subjects)]

        questions: list[Question] = []
        for csv_file in csv_files:
            subject = csv_file.stem
            with csv_file.open(encoding="utf-8") as fh:
                for row in csv.DictReader(fh):
                    answer_label = row.get("Answer", "").strip()
                    choices = [
                        Choice(label=lab, text=row.get(lab, "").strip())
                        for lab in ["A", "B", "C", "D"]
                    ]
                    answer_text = ""
                    for c in choices:
                        if c.label == answer_label:
                            answer_text = c.text
                            break
                    questions.append(
                        Question(
                            id=f"cmmlu_{subject}_{row.get('', '')}",
                            question=row.get("Question", "").strip(),
                            choices=choices,
                            answer=Answer(label=answer_label, text=answer_text),
                            source="cmmlu",
                            source_subset=subject,
                        )
                    )
                    if limit and len(questions) >= limit:
                        return questions
        return questions
