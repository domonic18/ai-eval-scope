"""知识点完善管道异常定义。"""

from __future__ import annotations

from agent_eval.core.exceptions import AgentEvalError


class KnowledgePipelineError(AgentEvalError):
    """知识点完善管道基础异常。"""


class DataSourceNotFoundError(KnowledgePipelineError):
    """数据源未注册。"""

    def __init__(self, name: str, available: list[str] | None = None):
        avail_str = f"，已注册: {available}" if available else ""
        super().__init__(
            f"未注册的数据源: {name}{avail_str}",
            details={"name": name, "available": available or []},
        )
        self.name = name


class SourceDataMissingError(KnowledgePipelineError):
    """数据源目录缺失或为空（无可读取的数据文件）——fail-fast，不做空读。"""

    def __init__(self, source: str, data_dir: object, expectation: str):
        super().__init__(
            f"{source} 数据目录缺失或为空（{expectation}）: {data_dir}",
            details={"source": source, "data_dir": str(data_dir)},
        )


class ExtractorNotFoundError(KnowledgePipelineError):
    """提取器未注册。"""

    def __init__(self, field: str, available: list[str] | None = None):
        avail_str = f"，已注册: {available}" if available else ""
        super().__init__(
            f"未注册的提取器（field={field}）{avail_str}",
            details={"field": field, "available": available or []},
        )
        self.field = field


class ConverterNotFoundError(KnowledgePipelineError):
    """转换器未注册。"""

    def __init__(self, name: str, available: list[str] | None = None):
        avail_str = f"，已注册: {available}" if available else ""
        super().__init__(
            f"未注册的转换器: {name}{avail_str}",
            details={"name": name, "available": available or []},
        )
        self.name = name


class KnowledgeMergeError(KnowledgePipelineError):
    """知识点合并失败。"""
