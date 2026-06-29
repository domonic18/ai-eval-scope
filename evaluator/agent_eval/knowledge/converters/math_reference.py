"""K-12 数学单位换算 → constants 转换器。

``MathReferenceSource`` 已提供完整的 ``{name, value, tolerance, extract_pattern,
description}``（国标权威值 + 贴合中文课件的 pattern），本转换器仅负责包装为
``ExtractedBatch``，统一走 pipeline 的转换→合并链路。
"""

from __future__ import annotations

from typing import Any

from agent_eval.knowledge.base import Converter
from agent_eval.knowledge.models import ExtractedBatch, ExtractedItem
from agent_eval.knowledge.registry import register_converter

_SOURCE_ID = "math_reference"


@register_converter("math_reference")
class MathReferenceConverter(Converter):
    """K-12 数学单位换算（时间/长度/质量/面积/体积/货币）→ math constants。"""

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
