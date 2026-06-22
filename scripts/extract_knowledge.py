"""从 questions.jsonl 提取 misconceptions（LLM 驱动）。

复用 agent_eval/llm Provider（经 llm_config.yaml 配置）。输出待人工审核的 YAML，
后续合并到 assets/knowledge/<subject>.yaml。

用法（从 evaluator/ 执行，以复用 agent_eval 与 LLM 依赖）:
    cd evaluator
    uv run python ../scripts/extract_knowledge.py \\
        --questions workspace/knowledge_extract/arc_questions.jsonl \\
        --output workspace/knowledge_extract/physics_misconceptions.yaml \\
        --limit 20
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv
from jinja2 import Template

from agent_eval.config import ConfigLoader
from agent_eval.llm import LLMClientFactory, Message


def load_prompt(path: Path) -> tuple[str, str]:
    """加载 prompt 模板，返回 (system_prompt, user_prompt)。"""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data["system_prompt"], data["user_prompt"]


def parse_misconceptions(content: str) -> list[dict]:
    """从 LLM 输出解析 misconceptions YAML 块（容错：去 markdown 围栏、截取块）。"""
    content = content.strip().strip("`").removeprefix("yaml").strip()
    match = re.search(r"misconceptions:\s*\n(.*)", content, re.DOTALL)
    if not match:
        return []
    yaml_block = "misconceptions:\n" + match.group(1)
    try:
        data = yaml.safe_load(yaml_block)
        items = (data or {}).get("misconceptions") or []
        return [it for it in items if isinstance(it, dict)]
    except yaml.YAMLError:
        return []


def main() -> None:
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    ap = argparse.ArgumentParser(description="LLM 提取 misconceptions（试点）")
    ap.add_argument("--questions", required=True, help="questions.jsonl（parse_dataset.py 输出）")
    ap.add_argument("--output", required=True, help="输出 YAML（待人工审核）")
    ap.add_argument("--provider", default=None, help="LLM provider 名（默认 llm_config.default）")
    ap.add_argument("--llm-config", default="agent_eval/assets/configs/llm_config.yaml")
    ap.add_argument("--prompt", default="agent_eval/assets/prompts/knowledge_extract.yaml")
    ap.add_argument("--limit", type=int, default=None, help="限制题数（试点用）")
    args = ap.parse_args()

    cfg = ConfigLoader.load_llm_config(args.llm_config)
    provider_name = args.provider or cfg.default
    client = LLMClientFactory.create(provider_name, cfg.providers[provider_name])
    print(
        f"使用 provider: {provider_name} / {cfg.providers[provider_name].model}",
        file=sys.stderr,
    )

    system_prompt, user_tpl = load_prompt(Path(args.prompt))

    questions = [
        json.loads(line)
        for line in Path(args.questions).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if args.limit:
        questions = questions[: args.limit]

    all_items: list[dict] = []
    for i, q in enumerate(questions, 1):
        distractors = [c["text"] for c in q["choices"] if c["label"] != q["answer"]["label"]]
        user = Template(user_tpl).render(
            question=q["question"],
            answer=q["answer"]["text"],
            distractors=distractors,
            source=q["id"],
        )
        try:
            resp = client.chat(
                [
                    Message(role="system", content=system_prompt),
                    Message(role="user", content=user),
                ]
            )
            items = parse_misconceptions(resp.content)
            all_items.extend(items)
            print(f"[{i}/{len(questions)}] {q['id']}: {len(items)} 条", file=sys.stderr)
        except Exception as e:  # noqa: BLE001 - 试点：单题失败不中断
            print(f"[{i}/{len(questions)}] {q['id']}: ❌ {e}", file=sys.stderr)

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        yaml.safe_dump({"misconceptions": all_items}, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    print(f"✅ 共 {len(all_items)} 条 misconception → {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
