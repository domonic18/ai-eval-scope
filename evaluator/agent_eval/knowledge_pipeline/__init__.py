"""知识点完善管道（knowledge_pipeline）。

将散乱的 scripts/ 脚本重构为统一的、可扩展的、CLI 集成的知识点完善管道系统。

核心抽象：
- ``DataSource``：统一数据源（评测题 → questions / 结构化表 → raw_items）
- ``Extractor``：LLM 提取器（misconceptions/constants from 评测题）
- ``Converter``：结构化转换器（constants from 周期表/NIST）
- ``KnowledgeMerger``：合并/去重/写盘
- ``KnowledgePipeline``：端到端编排

设计详见 docs/arch/11知识点完善管道系统设计.md。
"""

from agent_eval.knowledge_pipeline.base import Converter, DataSource, Extractor
from agent_eval.knowledge_pipeline.exceptions import (
    ConverterNotFoundError,
    DataSourceNotFoundError,
    ExtractorNotFoundError,
    KnowledgeMergeError,
    KnowledgePipelineError,
)
from agent_eval.knowledge_pipeline.models import (
    Answer,
    Choice,
    ExtractedBatch,
    ExtractedItem,
    KnowledgePatch,
    Question,
)
from agent_eval.knowledge_pipeline.registry import (
    discover_builtin,
    get_converter,
    get_extractor,
    get_source,
    list_converters,
    list_extractors,
    list_sources,
    register_converter,
    register_extractor,
    register_source,
)

__all__ = [
    # ABC
    "DataSource",
    "Extractor",
    "Converter",
    # 模型
    "Question",
    "Choice",
    "Answer",
    "ExtractedItem",
    "ExtractedBatch",
    "KnowledgePatch",
    # 异常
    "KnowledgePipelineError",
    "DataSourceNotFoundError",
    "ExtractorNotFoundError",
    "ConverterNotFoundError",
    "KnowledgeMergeError",
    # 注册
    "register_source",
    "register_extractor",
    "register_converter",
    "get_source",
    "get_extractor",
    "get_converter",
    "list_sources",
    "list_extractors",
    "list_converters",
    "discover_builtin",
]
