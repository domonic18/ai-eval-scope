"""KnowledgePipeline — 端到端编排：download → read → extract/convert → review → merge。

按 source.kind 自动分支：
- questions → Extractor（LLM 提取）
- raw_items → Converter（结构化转换）
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import yaml

from agent_eval.config.paths import paths
from agent_eval.knowledge.merger import KnowledgeMerger
from agent_eval.knowledge.models import ExtractedBatch, KnowledgePatch
from agent_eval.knowledge.registry import (
    discover_builtin,
    get_converter,
    get_extractor,
    get_source,
)


class KnowledgePipeline:
    """端到端知识点完善管道。

    Usage::

        pipe = KnowledgePipeline()
        result = pipe.run(
            source_name="periodic_table",
            field="constants",
            subject="chemistry",
        )
        # result = workspace/knowledge_extract/chemistry_constants.yaml（待审核）
    """

    def __init__(self) -> None:
        discover_builtin()
        self.output_dir = paths.default_workspace / "knowledge_extract"

    def run(
        self,
        source_name: str,
        field: str,
        subject: str,
        limit: int | None = None,
        apply: bool = False,
        data_dir: str | None = None,
        json_path: str | None = None,
        subjects: list[str] | None = None,
        provider: str | None = None,
        **kwargs,
    ) -> Path:
        """端到端：read → extract/convert → 输出 → （可选）merge。

        Args:
            source_name: 数据源名（arc / cmmlu / periodic_table）。
            field: 知识字段（misconceptions / constants）。
            subject: 目标学科（如 chemistry）。
            limit: 限制处理数量（试点用）。
            apply: True 时自动合并到 knowledge yaml。
            data_dir: 数据集目录（source 参数）。
            json_path: 数据源文件路径（source 参数，如周期表 JSON）。
            subjects: 学科筛选（source 参数，cmmlu 用）。
            provider: LLM provider 名（extractor 参数）。

        Returns:
            输出 YAML 路径（待审核或已合并）。
        """
        # 分离参数：source 专用 vs extractor 专用
        source_kwargs: dict[str, Any] = {}
        if data_dir is not None:
            source_kwargs["data_dir"] = data_dir
        if json_path is not None:
            source_kwargs["json_path"] = json_path
        if subjects is not None:
            source_kwargs["subjects"] = subjects

        extractor_kwargs: dict[str, Any] = {}
        if provider is not None:
            extractor_kwargs["provider"] = provider
        if limit is not None:
            extractor_kwargs["limit"] = limit

        # 1. 获取数据源并读取
        source = get_source(source_name, **source_kwargs)
        raw = source.read(limit=limit)
        print(f"📖 {source_name}.read() → {len(raw)} 条原始数据", file=sys.stderr)

        # 2. 按 kind 分支
        batch: ExtractedBatch
        if source.kind == "questions":
            extractor = get_extractor(field, **extractor_kwargs)
            batch = extractor.extract(raw)
        elif source.kind == "raw_items":
            converter = get_converter(source_name)
            batch = converter.convert(raw)
        else:
            raise ValueError(f"未知 source.kind: {source.kind}")

        print(f"✅ 提取/转换产出: {len(batch.items)} 条 {field}", file=sys.stderr)

        # 3. 输出待审核 YAML
        self.output_dir.mkdir(parents=True, exist_ok=True)
        output_path = self.output_dir / f"{subject}_{field}.yaml"
        patch = KnowledgePatch.from_batch(batch)
        output_path.write_text(
            yaml.safe_dump(
                {field: patch.items},
                allow_unicode=True,
                sort_keys=False,
                default_flow_style=False,
            ),
            encoding="utf-8",
        )
        print(f"📝 待审核 YAML: {output_path}", file=sys.stderr)

        # 4. 可选：自动合并
        if apply:
            merger = KnowledgeMerger()
            stats = merger.merge(patch, subject=subject)
            print(f"✅ 已合并到 {subject}.yaml: {stats}", file=sys.stderr)

        return output_path
