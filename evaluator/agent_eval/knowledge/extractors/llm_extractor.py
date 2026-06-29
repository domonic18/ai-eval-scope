"""LLM 提取器（misconceptions / constants）。

迁移自 scripts/extract_knowledge.py，复用 agent_eval/llm Provider。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from jinja2 import Template

from agent_eval.config import ConfigLoader
from agent_eval.config.paths import paths
from agent_eval.knowledge.base import Extractor
from agent_eval.knowledge.extractors.parsers import parse_items
from agent_eval.knowledge.models import ExtractedBatch, ExtractedItem, Question
from agent_eval.knowledge.registry import register_extractor
from agent_eval.llm import LLMClientFactory, Message

# field → prompt 文件名映射
_PROMPT_FILES = {
    "misconceptions": "knowledge_extract.yaml",
    "constants": "knowledge_extract_constants.yaml",
}


def _load_prompt(field: str) -> tuple[str, str]:
    """按 field 加载 prompt，返回 (system_prompt, user_prompt)。"""
    prompt_file = _PROMPT_FILES.get(field, f"knowledge_extract_{field}.yaml")
    prompt_path = paths.prompts_dir / prompt_file
    data = yaml.safe_load(prompt_path.read_text(encoding="utf-8"))
    return data["system_prompt"], data["user_prompt"]


@register_extractor("misconceptions")
class LlmMisconceptionsExtractor(Extractor):
    """从评测题干扰项提取常见误解（LLM 驱动）。"""

    field = "misconceptions"

    def __init__(
        self,
        provider: str | None = None,
        llm_config: Path | str | None = None,
        limit: int | None = None,
    ) -> None:
        self.provider_name = provider
        self.llm_config_path = (
            Path(llm_config) if llm_config else paths.configs_dir / "llm_config.yaml"
        )
        self.limit = limit

    def extract(self, questions: list[Question], **kwargs: Any) -> ExtractedBatch:
        load_dotenv(paths.assets_dir.parent.parent.parent / ".env")
        cfg = ConfigLoader.load_llm_config(str(self.llm_config_path))
        provider_name = self.provider_name or cfg.default
        client = LLMClientFactory.create(provider_name, cfg.providers[provider_name])

        system_prompt, user_tpl = _load_prompt(self.field)

        if self.limit:
            questions = questions[: self.limit]

        items: list[ExtractedItem] = []
        for i, q in enumerate(questions, 1):
            user = Template(user_tpl).render(
                question=q.question,
                answer=q.answer.text,
                distractors=q.distractors,
                choices=[c.text for c in q.choices],
                source=q.id,
            )
            try:
                resp = client.chat(
                    [
                        Message(role="system", content=system_prompt),
                        Message(role="user", content=user),
                    ]
                )
                parsed = parse_items(resp.content, self.field)
                for item_data in parsed:
                    items.append(
                        ExtractedItem(
                            field=self.field,
                            data=item_data,
                            source=q.id,
                        )
                    )
                print(f"[{i}/{len(questions)}] {q.id}: {len(parsed)} 条", file=sys.stderr)
            except Exception as e:  # noqa: BLE001
                print(f"[{i}/{len(questions)}] {q.id}: ❌ {e}", file=sys.stderr)

        return ExtractedBatch(
            field=self.field,
            items=items,
            source_dataset=questions[0].source if questions else "unknown",
            extractor=self.__class__.__name__,
        )


@register_extractor("constants")
class LlmConstantsExtractor(Extractor):
    """从评测题提取数值常数（LLM 驱动，评测题 ROI 低，结构化源更优）。

    保留此提取器用于评测题中少量数值事实的补充提取。
    """

    field = "constants"

    def __init__(
        self,
        provider: str | None = None,
        llm_config: Path | str | None = None,
        limit: int | None = None,
    ) -> None:
        self.provider_name = provider
        self.llm_config_path = (
            Path(llm_config) if llm_config else paths.configs_dir / "llm_config.yaml"
        )
        self.limit = limit

    def extract(self, questions: list[Question], **kwargs: Any) -> ExtractedBatch:
        load_dotenv(paths.assets_dir.parent.parent.parent / ".env")
        cfg = ConfigLoader.load_llm_config(str(self.llm_config_path))
        provider_name = self.provider_name or cfg.default
        client = LLMClientFactory.create(provider_name, cfg.providers[provider_name])

        system_prompt, user_tpl = _load_prompt(self.field)

        if self.limit:
            questions = questions[: self.limit]

        items: list[ExtractedItem] = []
        for i, q in enumerate(questions, 1):
            user = Template(user_tpl).render(
                question=q.question,
                answer=q.answer.text,
                distractors=q.distractors,
                choices=[c.text for c in q.choices],
                source=q.id,
            )
            try:
                resp = client.chat(
                    [
                        Message(role="system", content=system_prompt),
                        Message(role="user", content=user),
                    ]
                )
                parsed = parse_items(resp.content, self.field)
                for item_data in parsed:
                    items.append(
                        ExtractedItem(
                            field=self.field,
                            data=item_data,
                            source=q.id,
                        )
                    )
                print(f"[{i}/{len(questions)}] {q.id}: {len(parsed)} 条", file=sys.stderr)
            except Exception as e:  # noqa: BLE001
                print(f"[{i}/{len(questions)}] {q.id}: ❌ {e}", file=sys.stderr)

        return ExtractedBatch(
            field=self.field,
            items=items,
            source_dataset=questions[0].source if questions else "unknown",
            extractor=self.__class__.__name__,
        )
