"""知识库模块 — 读取（manager）+ 完善（pipeline/merger/sources/extractors/converters）。

运行时读取：``KnowledgeBaseManager.load()``
离线完善管道：``KnowledgePipeline.run()`` / ``KnowledgeMerger.merge()``
"""

from agent_eval.knowledge.base import Converter, DataSource, Extractor
from agent_eval.knowledge.exceptions import (
    ConverterNotFoundError,
    DataSourceNotFoundError,
    ExtractorNotFoundError,
    KnowledgeMergeError,
    KnowledgePipelineError,
)
from agent_eval.knowledge.manager import KnowledgeBaseManager
from agent_eval.knowledge.merger import KnowledgeMerger
from agent_eval.knowledge.models import (
    Answer,
    Choice,
    ExtractedBatch,
    ExtractedItem,
    KnowledgePatch,
    Question,
)
from agent_eval.knowledge.pipeline import KnowledgePipeline
from agent_eval.knowledge.registry import (
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
    # 读取
    "KnowledgeBaseManager",
    # 写入/编排
    "KnowledgeMerger",
    "KnowledgePipeline",
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
