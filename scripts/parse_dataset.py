"""解析评测数据集 → 统一 questions.jsonl（供知识点提取脚本消费）。

adapter 模式：每种数据集格式一个 parse_<id> 函数，输出统一结构：
    {id, question, choices:[{label,text}], answer:{label,text}, source, source_subset?}

支持的 adapter：
- arc: AI2 ARC（parquet: question/choices/answerKey，合并 ARC-Easy/ARC-Challenge 的 train）

用法（从 evaluator/ 执行，以复用 pyarrow）:
    cd evaluator
    uv run python ../scripts/parse_dataset.py \\
        --dataset arc --data-dir workspace/datasets/arc \\
        --output workspace/knowledge_extract/arc_questions.jsonl --limit 100
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pyarrow.parquet as pq


def parse_arc(data_dir: Path, limit: int | None = None) -> list[dict]:
    """ARC parquet → questions（合并 ARC-Easy / ARC-Challenge 的 train split）。"""
    questions: list[dict] = []
    for split_dir in sorted(data_dir.glob("ARC-*/")):
        for f in sorted(split_dir.glob("*train*.parquet")):
            table = pq.read_table(f).to_pydict()
            for i in range(len(table["id"])):
                choices = table["choices"][i]  # {text: [...], label: [...]}
                answer_key = table["answerKey"][i]
                answer_text = ""
                for lab, txt in zip(choices["label"], choices["text"]):
                    if lab == answer_key:
                        answer_text = txt
                        break
                questions.append(
                    {
                        "id": table["id"][i],
                        "question": table["question"][i],
                        "choices": [
                            {"label": lab, "text": txt}
                            for lab, txt in zip(choices["label"], choices["text"])
                        ],
                        "answer": {"label": answer_key, "text": answer_text},
                        "source": "arc",
                        "source_subset": split_dir.name,
                    }
                )
                if limit and len(questions) >= limit:
                    return questions
    return questions


ADAPTERS = {"arc": parse_arc}


def main() -> None:
    ap = argparse.ArgumentParser(description="解析数据集 → questions.jsonl")
    ap.add_argument("--dataset", required=True, help="数据集 id（如 arc）")
    ap.add_argument("--data-dir", required=True, help="数据集目录")
    ap.add_argument("--output", required=True, help="输出 questions.jsonl")
    ap.add_argument("--limit", type=int, default=None, help="限制题数（试点用）")
    args = ap.parse_args()

    adapter = ADAPTERS.get(args.dataset)
    if adapter is None:
        raise SystemExit(f"无 '{args.dataset}' adapter，支持: {list(ADAPTERS)}")

    questions = adapter(Path(args.data_dir), limit=args.limit)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        "\n".join(json.dumps(q, ensure_ascii=False) for q in questions),
        encoding="utf-8",
    )
    print(f"✅ 解析 {len(questions)} 题 → {out}")


if __name__ == "__main__":
    main()
