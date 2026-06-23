"""周期表 JSON → constants 转换器。

固化之前在 Bash 中内联验证的转换逻辑（符号→中文名映射 + Kelvin→℃ + 生成
{name, value, tolerance, extract_pattern}）。试点已验证产出 116 条 constants。
"""

from __future__ import annotations

from typing import Any

from agent_eval.knowledge_pipeline.base import Converter
from agent_eval.knowledge_pipeline.models import ExtractedBatch, ExtractedItem
from agent_eval.knowledge_pipeline.registry import register_converter

# K-12 常用元素符号 → 中文名
_K12_ELEMENTS = {
    "H": "氢",
    "He": "氦",
    "Li": "锂",
    "Be": "铍",
    "B": "硼",
    "C": "碳",
    "N": "氮",
    "O": "氧",
    "F": "氟",
    "Ne": "氖",
    "Na": "钠",
    "Mg": "镁",
    "Al": "铝",
    "Si": "硅",
    "P": "磷",
    "S": "硫",
    "Cl": "氯",
    "Ar": "氩",
    "K": "钾",
    "Ca": "钙",
    "Fe": "铁",
    "Cu": "铜",
    "Zn": "锌",
    "Br": "溴",
    "Ag": "银",
    "I": "碘",
    "Ba": "钡",
    "Au": "金",
    "Hg": "汞",
    "Pb": "铅",
}


@register_converter("periodic_table")
class PeriodicTableConverter(Converter):
    """周期表 JSON → chemistry constants。

    每个元素提取 4 类常数：相对原子质量、沸点(℃)、熔点(℃)、密度(g/cm³)。
    沸点/熔点从 Kelvin 转换为摄氏度。
    """

    field = "constants"

    def convert(self, raw_items: list[dict[str, Any]], **kwargs: Any) -> ExtractedBatch:
        items: list[ExtractedItem] = []

        for element in raw_items:
            symbol = element.get("symbol", "")
            if symbol not in _K12_ELEMENTS:
                continue

            cn_name = _K12_ELEMENTS[symbol]
            source_id = f"periodic_table_{symbol}"

            mass = element.get("atomic_mass")
            boil_k = element.get("boil")
            melt_k = element.get("melt")
            density = element.get("density")

            if mass is not None:
                mass_rounded = round(mass, 2)
                items.append(
                    ExtractedItem(
                        field="constants",
                        data={
                            "name": f"{cn_name}的相对原子质量",
                            "extract_pattern": f"{cn_name}.*?(?:相对原子质量|原子量)[^\\d]*(\\d+\\.?\\d*)",
                            "value": mass_rounded,
                            "tolerance": 0.01,
                            "description": f"{cn_name}（{symbol}）的相对原子质量约为 {mass_rounded}",
                            "source": source_id,
                        },
                        source=source_id,
                    )
                )

            if boil_k is not None:
                boil_c = round(boil_k - 273.15, 1)
                items.append(
                    ExtractedItem(
                        field="constants",
                        data={
                            "name": f"{cn_name}的沸点 (℃)",
                            "extract_pattern": f"{cn_name}.*沸点[^\\d]*(\\d+\\.?\\d*)\\s*(?:℃|度)?",
                            "value": boil_c,
                            "tolerance": 0.5,
                            "description": f"{cn_name}（{symbol}）的沸点约为 {boil_c}℃",
                            "source": source_id,
                        },
                        source=source_id,
                    )
                )

            if melt_k is not None:
                melt_c = round(melt_k - 273.15, 1)
                items.append(
                    ExtractedItem(
                        field="constants",
                        data={
                            "name": f"{cn_name}的熔点 (℃)",
                            "extract_pattern": f"{cn_name}.*熔点[^\\d]*(\\d+\\.?\\d*)\\s*(?:℃|度)?",
                            "value": melt_c,
                            "tolerance": 0.5,
                            "description": f"{cn_name}（{symbol}）的熔点约为 {melt_c}℃",
                            "source": source_id,
                        },
                        source=source_id,
                    )
                )

            if density is not None:
                items.append(
                    ExtractedItem(
                        field="constants",
                        data={
                            "name": f"{cn_name}的密度 (g/cm³)",
                            "extract_pattern": f"{cn_name}.*密度[^\\d]*(\\d+\\.?\\d*)",
                            "value": density,
                            "tolerance": round(density * 0.05, 3),
                            "description": f"{cn_name}（{symbol}）的密度约为 {density} g/cm³",
                            "source": source_id,
                        },
                        source=source_id,
                    )
                )

        return ExtractedBatch(
            field="constants",
            items=items,
            source_dataset="periodic_table",
            extractor=self.__class__.__name__,
        )
