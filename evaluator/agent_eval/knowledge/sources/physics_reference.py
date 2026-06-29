"""K-12 物理常用常数数据源（内嵌，教材权威值）。

初中物理（小学科学-初中）高频数据：常见物质密度、电池电压、折射率、
标准大气压水银柱高、人体体温等。值取教材权威值，extract_pattern 贴合中文课件表述。

设计说明：physics 无类似周期表的单权威 JSON 源，且 ``_check_constants`` 要求
value 为纯 float、pattern 捕获纯数字，故避开科学计数法常数（光速 3×10⁸、比热容
4.2×10³ 等课件以 ``a×10ⁿ`` 书写，捕获系数会令 value 失真），聚焦普通数值常数。
"""

from __future__ import annotations

from typing import Any

from agent_eval.knowledge.base import DataSource
from agent_eval.knowledge.registry import register_source

# K-12（小学科学-初中物理）常用常数 —— 教材权威值
# 每条：name / value(float) / tolerance / extract_pattern / description
_K12_PHYSICS_CONSTANTS: list[dict[str, Any]] = [
    # ─── 常见物质密度（g/cm³）───
    {
        "name": "铁的密度 (g/cm³)",
        "value": 7.9,
        "tolerance": 0.1,
        "extract_pattern": r"铁.*?密度[^\d]*(\d+\.?\d*)",
        "description": "铁的密度约为 7.9 g/cm³ = 7.9×10³ kg/m³",
    },
    {
        "name": "铜的密度 (g/cm³)",
        "value": 8.9,
        "tolerance": 0.1,
        "extract_pattern": r"铜.*?密度[^\d]*(\d+\.?\d*)",
        "description": "铜的密度约为 8.9 g/cm³ = 8.9×10³ kg/m³",
    },
    {
        "name": "铝的密度 (g/cm³)",
        "value": 2.7,
        "tolerance": 0.1,
        "extract_pattern": r"铝.*?密度[^\d]*(\d+\.?\d*)",
        "description": "铝的密度约为 2.7 g/cm³ = 2.7×10³ kg/m³",
    },
    {
        "name": "冰的密度 (g/cm³)",
        "value": 0.9,
        "tolerance": 0.05,
        "extract_pattern": r"冰.*?密度[^\d]*(\d+\.?\d*)",
        "description": "冰的密度约为 0.9 g/cm³ = 0.9×10³ kg/m³",
    },
    {
        "name": "水银的密度 (g/cm³)",
        "value": 13.6,
        "tolerance": 0.2,
        "extract_pattern": r"水银.*?密度[^\d]*(\d+\.?\d*)",
        "description": "水银（汞）的密度约为 13.6 g/cm³ = 13.6×10³ kg/m³",
    },
    {
        "name": "酒精的密度 (g/cm³)",
        "value": 0.8,
        "tolerance": 0.05,
        "extract_pattern": r"酒精.*?密度[^\d]*(\d+\.?\d*)",
        "description": "酒精的密度约为 0.8 g/cm³ = 0.8×10³ kg/m³",
    },
    {
        "name": "煤油的密度 (g/cm³)",
        "value": 0.8,
        "tolerance": 0.05,
        "extract_pattern": r"煤油.*?密度[^\d]*(\d+\.?\d*)",
        "description": "煤油的密度约为 0.8 g/cm³ = 0.8×10³ kg/m³",
    },
    # ─── 常见电压（V）───
    {
        "name": "一节干电池电压 (V)",
        "value": 1.5,
        "tolerance": 0,
        "extract_pattern": r"(?:一节|单节)?\s*干电池[^\d]*(\d+\.?\d*)\s*V",
        "description": "一节干电池电压为 1.5V",
    },
    {
        "name": "一节铅蓄电池电压 (V)",
        "value": 2.0,
        "tolerance": 0,
        "extract_pattern": r"(?:一节|单节)\s*(?:铅|铅酸)?蓄电池[^\d]*(\d+\.?\d*)\s*V",
        "description": "一节铅蓄电池电压为 2V",
    },
    {
        "name": "汽车蓄电池电压 (V)",
        "value": 12,
        "tolerance": 0,
        "extract_pattern": r"(?:汽车|轿车).*?(?:蓄电池|电瓶)[^\d]*(\d+)\s*V",
        "description": "汽车蓄电池电压约为 12V（6 节铅蓄电池串联）",
    },
    {
        "name": "工业动力电压 (V)",
        "value": 380,
        "tolerance": 5,
        "extract_pattern": r"(?:工业|动力|三相).*?(?:线电压|电压)[^\d]*(\d+)\s*V",
        "description": "工业三相动力线电压约为 380V",
    },
    # ─── 光学折射率 ───
    {
        "name": "水的折射率",
        "value": 1.33,
        "tolerance": 0.02,
        "extract_pattern": r"水.*?(?:的)?折射率[^\d]*(\d+\.?\d*)",
        "description": "水的折射率约为 1.33（≈4/3）",
    },
    {
        "name": "玻璃的折射率",
        "value": 1.5,
        "tolerance": 0.05,
        "extract_pattern": r"玻璃.*?(?:的)?折射率[^\d]*(\d+\.?\d*)",
        "description": "普通玻璃的折射率约为 1.5",
    },
    # ─── 标准大气压水银柱高（托里拆利实验）───
    {
        "name": "标准大气压水银柱高 (cm)",
        "value": 76,
        "tolerance": 1,
        "extract_pattern": r"(?:水银柱|汞柱).*?(?:高|高度|长约|约为)[^\d]*(\d+\.?\d*)\s*(?:cm|厘米)",
        "description": "1 标准大气压能托起约 76cm 高的水银柱",
    },
    {
        "name": "标准大气压水银柱高 (mmHg)",
        "value": 760,
        "tolerance": 10,
        "extract_pattern": r"(?:水银柱|汞柱).*?(?:高|高度|长约|约为)[^\d]*(\d+)\s*(?:mm|毫米)",
        "description": "1 标准大气压 = 760 mmHg",
    },
    # ─── 体温（热学常用）───
    {
        "name": "人体正常体温 (℃)",
        "value": 37,
        "tolerance": 0.5,
        "extract_pattern": r"(?:正常体温|人的体温|人体体温)[^\d]*(\d+\.?\d*)",
        "description": "人体正常体温约为 37℃",
    },
]


@register_source("physics_reference")
class PhysicsReferenceSource(DataSource):
    """K-12 物理常用常数数据源（内嵌教材权威值，无需外部下载）。"""

    kind = "raw_items"

    def read(self, limit: int | None = None, **kwargs: Any) -> list[dict[str, Any]]:
        data = _K12_PHYSICS_CONSTANTS
        if limit:
            data = data[:limit]
        return [dict(d) for d in data]
