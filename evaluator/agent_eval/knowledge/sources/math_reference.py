"""K-12 数学常用单位换算数据源（内嵌，国标/教材权威值）。

小学数学单位换算高频数据：时间 / 长度 / 质量 / 面积 / 体积容积 / 货币。
值取国标 GB 3102 与教材权威值，extract_pattern 贴合中文课件表述。

设计说明：单位换算为整数精确值（tolerance=0），``_check_constants`` 完全支持。
"""

from __future__ import annotations

from typing import Any

from agent_eval.knowledge.base import DataSource
from agent_eval.knowledge.registry import register_source

# K-12（小学数学）常用单位换算 —— 国标/教材权威值
# 每条：name / value(int) / tolerance / extract_pattern / description
_K12_UNIT_CONVERSIONS: list[dict[str, Any]] = [
    # ─── 时间 ───
    {
        "name": "1时 = 60分",
        "value": 60,
        "tolerance": 0,
        "extract_pattern": r"(?:1小时|1时|一小时)\s*(?:=|＝|等于|为)\s*(\d+)\s*分钟?",
        "description": "1 小时 = 60 分钟",
    },
    {
        "name": "1分 = 60秒",
        "value": 60,
        "tolerance": 0,
        "extract_pattern": r"(?:1分钟|1分|一分)\s*(?:=|＝|等于|为)\s*(\d+)\s*(?:秒|s)",
        "description": "1 分钟 = 60 秒",
    },
    {
        "name": "1时 = 3600秒",
        "value": 3600,
        "tolerance": 0,
        "extract_pattern": r"(?:1小时|1时)\s*(?:=|＝|等于).*?(\d+)\s*(?:秒|s)",
        "description": "1 小时 = 3600 秒",
    },
    {
        "name": "1天 = 24时",
        "value": 24,
        "tolerance": 0,
        "extract_pattern": r"(?:1天|一天|一日)\s*(?:=|＝|等于|为|有)\s*(\d+)\s*(?:小时|时|h)",
        "description": "1 天 = 24 小时",
    },
    {
        "name": "1年 ≈ 365天",
        "value": 365,
        "tolerance": 1,
        "extract_pattern": r"(?:1年|一年)\s*(?:≈|＝|=|约为|约|等于)\s*(\d+)\s*(?:天|日)",
        "description": "1 年 ≈ 365 天（平年）",
    },
    # ─── 长度 ───
    {
        "name": "1千米 = 1000米",
        "value": 1000,
        "tolerance": 0,
        "extract_pattern": r"(?:1千米|1公里|1km)\s*(?:=|＝|等于|为)\s*(\d+)\s*(?:米|m)",
        "description": "1 千米 = 1000 米",
    },
    {
        "name": "1米 = 10分米",
        "value": 10,
        "tolerance": 0,
        "extract_pattern": r"(?:1米|1m)\s*(?:=|＝|等于|为)\s*(\d+)\s*(?:分米|dm)",
        "description": "1 米 = 10 分米",
    },
    {
        "name": "1米 = 100厘米",
        "value": 100,
        "tolerance": 0,
        "extract_pattern": r"(?:1米|1m)\s*(?:=|＝|等于|为)\s*(\d+)\s*(?:厘米|cm)",
        "description": "1 米 = 100 厘米",
    },
    {
        "name": "1米 = 1000毫米",
        "value": 1000,
        "tolerance": 0,
        "extract_pattern": r"(?:1米|1m)\s*(?:=|＝|等于|为)\s*(\d+)\s*(?:毫米|mm)",
        "description": "1 米 = 1000 毫米",
    },
    # ─── 质量 ───
    {
        "name": "1吨 = 1000千克",
        "value": 1000,
        "tolerance": 0,
        "extract_pattern": r"(?:1吨|1t)\s*(?:=|＝|等于|为)\s*(\d+)\s*(?:千克|kg)",
        "description": "1 吨 = 1000 千克",
    },
    {
        "name": "1千克 = 1000克",
        "value": 1000,
        "tolerance": 0,
        "extract_pattern": r"(?:1千克|1公斤|1kg)\s*(?:=|＝|等于|为)\s*(\d+)\s*(?:克|g)",
        "description": "1 千克 = 1000 克",
    },
    # ─── 面积 ───
    {
        "name": "1平方千米 = 100公顷",
        "value": 100,
        "tolerance": 0,
        "extract_pattern": r"(?:1平方千米|1平方公里|1km²)\s*(?:=|＝|等于|为)\s*(\d+)\s*(?:公顷)",
        "description": "1 平方千米 = 100 公顷",
    },
    {
        "name": "1公顷 = 10000平方米",
        "value": 10000,
        "tolerance": 0,
        "extract_pattern": r"(?:1公顷|1ha)\s*(?:=|＝|等于|为)\s*(\d+)\s*(?:平方米|m²)",
        "description": "1 公顷 = 10000 平方米",
    },
    {
        "name": "1平方米 = 100平方分米",
        "value": 100,
        "tolerance": 0,
        "extract_pattern": r"(?:1平方米|1m²)\s*(?:=|＝|等于|为)\s*(\d+)\s*(?:平方分米|dm²)",
        "description": "1 平方米 = 100 平方分米",
    },
    {
        "name": "1平方分米 = 100平方厘米",
        "value": 100,
        "tolerance": 0,
        "extract_pattern": r"(?:1平方分米|1dm²)\s*(?:=|＝|等于|为)\s*(\d+)\s*(?:平方厘米|cm²)",
        "description": "1 平方分米 = 100 平方厘米",
    },
    # ─── 体积 / 容积 ───
    {
        "name": "1立方米 = 1000立方分米",
        "value": 1000,
        "tolerance": 0,
        "extract_pattern": r"(?:1立方米|1m³)\s*(?:=|＝|等于|为)\s*(\d+)\s*(?:立方分米|dm³)",
        "description": "1 立方米 = 1000 立方分米",
    },
    {
        "name": "1升 = 1000毫升",
        "value": 1000,
        "tolerance": 0,
        "extract_pattern": r"(?:1升|1L)\s*(?:=|＝|等于|为)\s*(\d+)\s*(?:毫升|mL)",
        "description": "1 升 = 1000 毫升",
    },
    {
        "name": "1立方分米 = 1升",
        "value": 1,
        "tolerance": 0,
        "extract_pattern": r"(?:1立方分米|1dm³)\s*(?:=|＝|等于|为)\s*(\d+)\s*(?:升|L)",
        "description": "1 立方分米 = 1 升",
    },
    # ─── 货币（人民币）───
    {
        "name": "1元 = 10角",
        "value": 10,
        "tolerance": 0,
        "extract_pattern": r"(?:1元|一元)\s*(?:=|＝|等于|为)\s*(\d+)\s*角",
        "description": "1 元 = 10 角",
    },
    {
        "name": "1角 = 10分",
        "value": 10,
        "tolerance": 0,
        "extract_pattern": r"(?:1角|一角)\s*(?:=|＝|等于|为)\s*(\d+)\s*分",
        "description": "1 角 = 10 分",
    },
    {
        "name": "1元 = 100分",
        "value": 100,
        "tolerance": 0,
        "extract_pattern": r"(?:1元|一元)\s*(?:=|＝|等于|为)\s*(\d+)\s*分",
        "description": "1 元 = 100 分",
    },
    # ─── 角度（补充已有周角/平角/分秒）───
    {
        "name": "直角 (90度)",
        "value": 90,
        "tolerance": 0,
        "extract_pattern": r"(?:直角|一直角)\s*(?:=|＝|等于|为|是)\s*(\d+)\s*(?:度|°)",
        "description": "1 直角 = 90 度",
    },
]


@register_source("math_reference")
class MathReferenceSource(DataSource):
    """K-12 数学单位换算数据源（内嵌国标/教材权威值，无需外部下载）。"""

    kind = "raw_items"

    def read(self, limit: int | None = None, **kwargs: Any) -> list[dict[str, Any]]:
        data = _K12_UNIT_CONVERSIONS
        if limit:
            data = data[:limit]
        return [dict(d) for d in data]
