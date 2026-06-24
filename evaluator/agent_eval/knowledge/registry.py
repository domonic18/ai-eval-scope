"""知识点完善管道注册机制（装饰器注册 + 工厂）。

扩展新数据源/提取器/转换器只需在对应目录下新建文件并标注装饰器，
不改核心代码（参照 datasets/downloader.py 的惰性导入范式）。
"""

from __future__ import annotations

from typing import Any

from agent_eval.knowledge.base import Converter, DataSource, Extractor
from agent_eval.knowledge.exceptions import (
    ConverterNotFoundError,
    DataSourceNotFoundError,
    ExtractorNotFoundError,
)

# ─── 注册表 ───

_SOURCES: dict[str, type[DataSource]] = {}
_EXTRACTORS: dict[str, type[Extractor]] = {}
_CONVERTERS: dict[str, type[Converter]] = {}


# ─── 装饰器 ───


def register_source(name: str):
    """装饰器：注册数据源。

    Usage::

        @register_source("arc")
        class ArcSource(DataSource): ...
    """

    def decorator(cls: type[DataSource]) -> type[DataSource]:
        _SOURCES[name] = cls
        return cls

    return decorator


def register_extractor(name: str):
    """装饰器：注册 LLM 提取器。"""

    def decorator(cls: type[Extractor]) -> type[Extractor]:
        _EXTRACTORS[name] = cls
        return cls

    return decorator


def register_converter(name: str):
    """装饰器：注册结构化转换器。"""

    def decorator(cls: type[Converter]) -> type[Converter]:
        _CONVERTERS[name] = cls
        return cls

    return decorator


# ─── 工厂 ───


def get_source(name: str, **kwargs: Any) -> DataSource:
    """工厂：按名获取数据源实例。"""
    if name not in _SOURCES:
        raise DataSourceNotFoundError(name, available=list(_SOURCES))
    return _SOURCES[name](**kwargs)


def get_extractor(field: str, **kwargs: Any) -> Extractor:
    """工厂：按 field（misconceptions/constants）获取提取器。"""
    if field not in _EXTRACTORS:
        raise ExtractorNotFoundError(field, available=list(_EXTRACTORS))
    return _EXTRACTORS[field](**kwargs)


def get_converter(name: str, **kwargs: Any) -> Converter:
    """工厂：按名获取转换器（periodic_table / nist_codata）。"""
    if name not in _CONVERTERS:
        raise ConverterNotFoundError(name, available=list(_CONVERTERS))
    return _CONVERTERS[name](**kwargs)


# ─── 查询 ───


def list_sources() -> list[str]:
    """列出已注册的数据源名。"""
    return sorted(_SOURCES)


def list_extractors() -> list[str]:
    """列出已注册的提取器 field 名。"""
    return sorted(_EXTRACTORS)


def list_converters() -> list[str]:
    """列出已注册的转换器名。"""
    return sorted(_CONVERTERS)


def discover_builtin() -> None:
    """导入内置模块，触发 @register_* 装饰器注册。

    在 __init__.py 或首次使用管道时调用。
    """
    import agent_eval.knowledge.converters.math_reference  # noqa: F401
    import agent_eval.knowledge.converters.periodic_table  # noqa: F401
    import agent_eval.knowledge.converters.physics_reference  # noqa: F401
    import agent_eval.knowledge.extractors.llm_extractor  # noqa: F401
    import agent_eval.knowledge.sources.eval_sources  # noqa: F401
    import agent_eval.knowledge.sources.math_reference  # noqa: F401
    import agent_eval.knowledge.sources.physics_reference  # noqa: F401
    import agent_eval.knowledge.sources.table_sources  # noqa: F401
