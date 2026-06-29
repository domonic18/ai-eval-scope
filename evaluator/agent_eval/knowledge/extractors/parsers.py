"""LLM 提取器输出解析工具。"""

from __future__ import annotations

import re

import yaml


def parse_items(content: str, key: str) -> list[dict]:
    """从 LLM 输出解析指定 key 的 YAML 块。

    容错处理：去 markdown 围栏、截取 key 块、yaml.safe_load。
    """
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
