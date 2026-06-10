"""公式归一化与索引构建工具。

将 Unicode 数学符号归一化为 ASCII，构建基于 domain_facts 的公式查找索引，
供 MathFormulaEvaluator 的符号公式校验使用。
"""

from __future__ import annotations

import re
from typing import Any

# Unicode 数学符号 → ASCII 映射
_MATH_SYMBOL_MAP = {
    "×": "*",
    "÷": "/",
    "＋": "+",
    "－": "-",
    "＝": "=",
    "²": "^2",
    "³": "^3",
    "½": "1/2",
    "⅓": "1/3",
    "⅔": "2/3",
    "¼": "1/4",
    "¾": "3/4",
    "·": "*",
    "⋅": "*",
}


def normalize_formula(expr: str) -> str:
    """将公式表达式归一化为 ASCII 标准形式。

    - Unicode 数学符号 → ASCII
    - 去除所有空白
    """
    s = expr.strip()
    for old, new in _MATH_SYMBOL_MAP.items():
        s = s.replace(old, new)
    s = re.sub(r"\s+", "", s)
    return s


def normalize_formula_name(name: str) -> str:
    """将中文公式名归一化用于匹配。

    - 去除 "的"（"圆的面积" → "圆面积"）
    """
    return name.replace("的", "").strip()


def build_formula_index(domain_facts: dict[str, Any]) -> list[dict[str, Any]]:
    """从 domain_facts 构建公式查找索引。

    Args:
        domain_facts: 来自 _load_fact_db() 的 domain_facts dict，
            包含 math_formulas 等子分类。

    Returns:
        公式条目列表，每项含：
        - original_name: 原始中文名
        - canonical_name: 归一化中文名
        - formula: 原始公式字符串
        - normalized_formula: 归一化公式字符串
        - variables: 公式中出现的变量字母集合
        - category: 子分类名
        - description: 描述
    """
    results: list[dict[str, Any]] = []
    math_formulas = domain_facts.get("math_formulas", {})
    if not isinstance(math_formulas, dict):
        return results

    for category, entries in math_formulas.items():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            name = entry.get("name", "")
            formula = entry.get("formula", "")
            if not name or not formula:
                continue
            norm_name = normalize_formula_name(name)
            norm_formula = normalize_formula(formula)
            variables = set(re.findall(r"[a-zA-Z]", norm_formula))
            results.append({
                "original_name": name,
                "canonical_name": norm_name,
                "formula": formula,
                "normalized_formula": norm_formula,
                "variables": variables,
                "category": category,
                "description": entry.get("description", ""),
            })
    return results
