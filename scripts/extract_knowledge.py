"""从 questions.jsonl 提取知识点（LLM 驱动）。

支持字段（--field）：
- misconceptions（默认）：选择题干扰项 → 常见误解（pattern 关键词即可，即生即用）
- constants：含数值事实 → 数值常数（extract_pattern 正则 LLM 生成，需在真实课件上验证）

复用 agent_eval/llm Provider。输出待人工审核 YAML，合并到 assets/knowledge/。

用法（从 evaluator/ 执行，以复用 agent_eval 与 LLM 依赖）:
    cd evaluator
    uv run python ../scripts/extract_knowledge.py \\
        --questions workspace/knowledge_extract/arc_questions.jsonl \\
        --output workspace/knowledge_extract/physics_constants.yaml \\
        --field constants --limit 20
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


def parse_items(content: str, key: str) -> list[dict]:
    """从 LLM 输出解析指定 key 的 YAML 块（容错：去 markdown 围栏、截取块）。"""
    content = content.strip().strip("`").removeprefix("yaml").strip()
    match = re.search(rf"{key}:\s*\n(.*)", content, re.DOTALL)
    if not match:
        return []
    yaml_block = f"{key}:\n" + match.group(1)
    try:
        data = yaml.safe_load(yaml_block)
        items = (data or {}).get(key) or []
        return [it for it in items if isinstance(it, dict)]
    except yaml.YAMLError:
        return []


def main() -> None:
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    ap = argparse.ArgumentParser(description="LLM 提取知识点（试点）")
    ap.add_argument("--questions", required=True, help="questions.jsonl（parse_dataset.py 输出）")
    ap.add_argument("--output", required=True, help="输出 YAML（待人工审核）")
    ap.add_argument("--provider", default=None, help="LLM provider 名（默认 llm_config.default）")
    ap.add_argument("--llm-config", default="agent_eval/assets/configs/llm_config.yaml")
    ap.add_argument(
        "--field",
        default="misconceptions",
        help="提取字段：misconceptions（默认）/ constants",
    )
    ap.add_argument(
        "--prompt",
        default=None,
        help="prompt 文件（默认按 field 选 knowledge_extract[_constants].yaml）",
    )
    ap.add_argument("--limit", type=int, default=None, help="限制题数（试点用）")
    args = ap.parse_args()

    prompt_path = args.prompt or (
        f"agent_eval/assets/prompts/"
        f"knowledge_extract{'_constants' if args.field == 'constants' else ''}.yaml"
    )

    cfg = ConfigLoader.load_llm_config(args.llm_config)
    provider_name = args.provider or cfg.default
    client = LLMClientFactory.create(provider_name, cfg.providers[provider_name])
    print(
        f"使用 provider: {provider_name} / {cfg.providers[provider_name].model} | field={args.field}",
        file=sys.stderr,
    )

    system_prompt, user_tpl = load_prompt(Path(prompt_path))

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
            choices=[c["text"] for c in q["choices"]],
            source=q["id"],
        )
        try:
            resp = client.chat(
                [
                    Message(role="system", content=system_prompt),
                    Message(role="user", content=user),
                ]
            )
            items = parse_items(resp.content, args.field)
            all_items.extend(items)
            print(f"[{i}/{len(questions)}] {q['id']}: {len(items)} 条", file=sys.stderr)
        except Exception as e:  # noqa: BLE001 - 试点：单题失败不中断
            print(f"[{i}/{len(questions)}] {q['id']}: ❌ {e}", file=sys.stderr)

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        yaml.safe_dump({args.field: all_items}, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    print(f"✅ 共 {len(all_items)} 条 {args.field} → {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
