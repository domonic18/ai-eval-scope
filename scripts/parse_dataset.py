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


def parse_cmmlu(data_dir: Path, limit: int | None = None, subjects: list[str] | None = None) -> list[dict]:
    """CMMLU CSV（需先解压 zip 到 extracted/）→ questions。

    CSV 格式：index,Question,A,B,C,D,Answer（Answer 为 A/B/C/D）。
    按 subjects 过滤（如 high_school_physics）；subjects=None 取全部学科。
    默认读 test split。
    """
    import csv

    test_dir = data_dir / "extracted" / "test"
    if not test_dir.exists():
        raise SystemExit(f"cmmlu 未解压：期望 {test_dir}（先 unzip cmmlu_v1_0_1.zip -d extracted）")

    csv_files = sorted(test_dir.glob("*.csv"))
    if subjects:
        csv_files = [f for f in csv_files if any(s in f.name for s in subjects)]

    questions: list[dict] = []
    for csv_file in csv_files:
        subject = csv_file.stem
        with csv_file.open(encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                answer_label = row.get("Answer", "").strip()
                choices = [
                    {"label": lab, "text": row.get(lab, "").strip()}
                    for lab in ["A", "B", "C", "D"]
                ]
                answer_text = ""
                for c in choices:
                    if c["label"] == answer_label:
                        answer_text = c["text"]
                        break
                questions.append(
                    {
                        "id": f"cmmlu_{subject}_{row.get('', '')}",
                        "question": row.get("Question", "").strip(),
                        "choices": choices,
                        "answer": {"label": answer_label, "text": answer_text},
                        "source": "cmmlu",
                        "source_subset": subject,
                    }
                )
                if limit and len(questions) >= limit:
                    return questions
    return questions


ADAPTERS["cmmlu"] = parse_cmmlu


def main() -> None:
    ap = argparse.ArgumentParser(description="解析数据集 → questions.jsonl")
    ap.add_argument("--dataset", required=True, help="数据集 id（如 arc）")
    ap.add_argument("--data-dir", required=True, help="数据集目录")
    ap.add_argument("--output", required=True, help="输出 questions.jsonl")
    ap.add_argument("--limit", type=int, default=None, help="限制题数（试点用）")
    ap.add_argument(
        "--subjects",
        default=None,
        help="学科筛选（逗号分隔，如 high_school_physics,high_school_chemistry；cmmlu 用）",
    )
    args = ap.parse_args()

    adapter = ADAPTERS.get(args.dataset)
    if adapter is None:
        raise SystemExit(f"无 '{args.dataset}' adapter，支持: {list(ADAPTERS)}")

    subjects = args.subjects.split(",") if args.subjects else None
    if args.dataset == "cmmlu":
        questions = adapter(Path(args.data_dir), limit=args.limit, subjects=subjects)
    else:
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
