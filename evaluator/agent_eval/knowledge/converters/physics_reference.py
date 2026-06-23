"""K-12 物理常用常数 → constants 转换器。

``PhysicsReferenceSource`` 已提供完整的 ``{name, value, tolerance,
extract_pattern, description}``（教材权威值 + 贴合中文课件的 pattern），
本转换器仅负责包装为 ``ExtractedBatch``，统一走 pipeline 的转换→合并链路，
保证 source 可追溯、合并去重一致。
"""

from __future__ import annotations

from typing import Any

from agent_eval.knowledge.base import Converter
from agent_eval.knowledge.models import ExtractedBatch, ExtractedItem
from agent_eval.knowledge.registry import register_converter

_SOURCE_ID = "physics_reference"


@register_converter("physics_reference")
class PhysicsReferenceConverter(Converter):
    """K-12 物理常用常数（密度/电压/折射率/水银柱/体温）→ physics constants。"""

    field = "constants"

    def convert(self, raw_items: list[dict[str, Any]], **kwargs: Any) -> ExtractedBatch:
        items: list[ExtractedItem] = []
        for d in raw_items:
            items.append(
                ExtractedItem(
                    field="constants",
                    data={**d, "source": _SOURCE_ID},
                    source=_SOURCE_ID,
                )
            )
        return ExtractedBatch(
            field="constants",
            items=items,
            source_dataset=_SOURCE_ID,
            extractor=self.__class__.__name__,
        )
