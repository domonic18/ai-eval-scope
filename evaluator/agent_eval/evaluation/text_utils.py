"""文档文本提取工具 — 供评估器收集样本正文。

为何存在：早期实现用裸正则 `re.sub(r"<[^>]+>", " ", html)` 剥 HTML 标签，但**不
剥离 `<style>/<script>` 块内容**，导致富样式 HTML 的大段 CSS 作为"正文"留存，被
截断后 LLM 只看到样式噪声而看不到真实教学内容，使文本类 LLM 评估（soft/pref/
logical_consistency）系统性失真。

本模块基于标准库 `html.parser.HTMLParser` 实现干净提取：
- 丢弃 `<script>`/`<style>`/`<head>`/`<noscript>`/`<template>` 内容（SVG 文本保留）
- 块级标签（p/div/li/h*/tr/br…）触发换行，保留可读结构
- 解码 HTML 实体（&nbsp; &amp; 等）
- 折叠多余空白
纯 stdlib，零新依赖，复用单一实现避免多副本再次分叉。
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from agent_eval.config import EVALUATOR_DEFAULTS


def get_output_dir(sample: Any) -> Path | None:
    """从样本中提取 output 目录。

    评估器通用工具，置于 text_utils 以避免 commonsense_evaluators 与
    quality_evaluators 之间的循环依赖。
    """
    if isinstance(sample, Path):
        return sample / "output" if sample.is_dir() else sample.parent / "output"
    if hasattr(sample, "output_dir") and sample.output_dir is not None:
        return Path(sample.output_dir)
    if isinstance(sample, dict):
        p = sample.get("package_dir") or sample.get("output_dir")
        if p:
            p = Path(p)
            return p / "output" if p.is_dir() and (p / "output").exists() else p
    return None


# 其内容应整体丢弃的标签（连同子内容）。这些标签都有配对的关闭标签，可安全用
# 深度计数丢弃。注意：自闭合无内容标签（meta/link/br/hr 等）**不放入此集合**——它们
# 无 `</tag>` 配对，若放入会让深度计数器只增不减，吞掉后续所有正文。
_DROP_TAGS = frozenset({"script", "style", "head", "noscript", "template"})
# 块级/换行标签：遇到则插入换行，保留文档可读结构
_BLOCK_TAGS = frozenset(
    {
        "p",
        "div",
        "section",
        "article",
        "main",
        "header",
        "footer",
        "nav",
        "aside",
        "li",
        "ul",
        "ol",
        "dl",
        "dt",
        "dd",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "tr",
        "table",
        "thead",
        "tbody",
        "tfoot",
        "td",
        "th",
        "br",
        "hr",
        "blockquote",
        "pre",
        "figure",
        "figcaption",
        "details",
        "summary",
    }
)

# 折叠空白：连续空白（含换行）归一
_WS_RE = re.compile(r"[ \t\f\v]+")
_BLANK_LINES_RE = re.compile(r"\n{3,}")


class _TextExtractor(HTMLParser):
    """把 HTML 转换为纯文本，丢弃 style/script 等噪声，保留块级结构。"""

    def __init__(self) -> None:
        # convert_charrefs=True 让 data 回调直接拿到解码后的文本（实体已转换）
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        # 正在被丢弃的标签的嵌套深度（>0 表示当前在 drop 标签内部）
        self._drop_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in _DROP_TAGS:
            self._drop_depth += 1
            return
        if tag in _BLOCK_TAGS:
            self._parts.append("\n")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        # 自闭合标签（如 <br/>）
        if tag.lower() in _BLOCK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in _DROP_TAGS:
            if self._drop_depth > 0:
                self._drop_depth -= 1
            return
        if tag in _BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._drop_depth > 0:
            return
        if data:
            self._parts.append(data)

    def get_text(self) -> str:
        text = "".join(self._parts)
        text = _WS_RE.sub(" ", text)
        text = text.replace(" \n", "\n").replace("\n ", "\n")
        text = _BLANK_LINES_RE.sub("\n\n", text)
        return text.strip()


def html_to_text(html: str) -> str:
    """将 HTML 字符串转换为干净的纯文本（剥除 style/script/head，保留块级结构）。"""
    if not html:
        return ""
    parser = _TextExtractor()
    # 容错：HTMLParser 对畸形 HTML 也只会忽略无法识别的部分，不会抛
    parser.feed(html)
    parser.close()
    return parser.get_text()


def file_to_text(path: Path) -> str:
    """读取单个文档文件并返回纯文本（HTML 剥样式，Markdown/文本原样）。"""
    try:
        raw = Path(path).read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""
    if path.suffix.lower() in (".html", ".htm"):
        return html_to_text(raw)
    return raw


_DOC_EXTS = tuple(EVALUATOR_DEFAULTS.text_collection_patterns)


def collect_text_content(output_dir: Path) -> str:
    """收集目录下所有文档的文本内容，合并为单个字符串（文档间以分隔标记连接）。

    用于需要把整套产出物作为整体评估的场景（如教学逻辑、内容多样性）。
    """
    texts: list[str] = []
    for ext in _DOC_EXTS:
        for f in sorted(Path(output_dir).rglob(ext)):
            t = file_to_text(f)
            if t.strip():
                texts.append(t)
    return "\n\n".join(texts)


def collect_file_texts(output_dir: Path) -> dict[str, str]:
    """按文件收集纯文本，保留文件归属。

    Returns:
        {文件相对路径: 纯文本内容}（HTML 已剥样式，仅含非空文档）。
    """
    out: dict[str, str] = {}
    base = Path(output_dir)
    for ext in _DOC_EXTS:
        for f in sorted(base.rglob(ext)):
            t = file_to_text(f)
            if t.strip():
                out[str(f.relative_to(base))] = t
    return out
