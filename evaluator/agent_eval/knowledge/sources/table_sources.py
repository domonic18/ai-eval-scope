"""结构化数值表数据源（周期表 JSON / NIST CODATA → raw_items）。

这些源的 ``read()`` 返回 ``list[dict]``（原始结构化数据），
由 ``Converter`` 子类消费转换为知识点。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent_eval.config.paths import paths
from agent_eval.knowledge.base import DataSource
from agent_eval.knowledge.registry import register_source

_PERIODIC_TABLE_URL = (
    "https://raw.githubusercontent.com/Bowserinator/Periodic-Table-JSON/"
    "master/PeriodicTableJSON.json"
)


@register_source("periodic_table")
class PeriodicTableSource(DataSource):
    """周期表 JSON 数据源（Bowserinator/Periodic-Table-JSON）。

    元素含 name/symbol/atomic_mass/boil(Kelvin)/melt(Kelvin)/density 等属性。
    需先下载 JSON 到 ``{data_dir}/PeriodicTableJSON.json``。
    """

    kind = "raw_items"

    def __init__(
        self,
        data_dir: Path | str | None = None,
        json_path: Path | str | None = None,
    ) -> None:
        if json_path:
            self.json_path = Path(json_path)
        else:
            base = Path(data_dir) if data_dir else paths.default_workspace / "knowledge_extract"
            self.json_path = base / "PeriodicTableJSON.json"

    def read(self, limit: int | None = None, **kwargs: Any) -> list[dict[str, Any]]:
        if not self.json_path.exists():
            raise FileNotFoundError(
                f"周期表 JSON 不存在: {self.json_path}\n"
                f"请先下载: curl -sL {_PERIODIC_TABLE_URL} -o {self.json_path}"
            )
        data = json.loads(self.json_path.read_text(encoding="utf-8"))
        elements = data.get("elements", [])
        if limit:
            elements = elements[:limit]
        return elements
