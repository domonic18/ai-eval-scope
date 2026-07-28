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


def collect_text_content(output_dir: Path) -> str:
    """收集 output_dir 下所有产出文件的文本内容，合并为单个字符串。

    output/ 已由 build_package 按场景 format 门控预过滤（code→.py / courseware→.html,.md），
    故此处收集全部文件（跳过目录清单 _manifest.json），由 file_to_text 按扩展名处理
    （html 剥标签，其余原样），二进制/异常安全。去 courseware html/md 白名单硬编码。
    """
    texts: list[str] = []
    for f in sorted(Path(output_dir).rglob("*")):
        if not f.is_file() or f.name == "_manifest.json":
            continue
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
    for f in sorted(base.rglob("*")):
        if not f.is_file() or f.name == "_manifest.json":
            continue
        t = file_to_text(f)
        if t.strip():
            out[str(f.relative_to(base))] = t
    return out


def collect_text_content_with_markers(output_dir: Path) -> str:
    """合并文档文本，每文件前注入 ``=== FILE: 相对路径 ===`` 边界标记。

    供 C 档 LLM 评估器（soft/pref）使用：判官读到带标记的文本后，可在 issue 的
    ``involved_files`` 里引用具体文件名，实现「扣分→定位文件」（docs/arch/15 §5.1）。
    无文档时返回空串。
    """
    parts: list[str] = [
        f"=== FILE: {fname} ===\n{text}" for fname, text in collect_file_texts(output_dir).items()
    ]
    return "\n\n".join(parts)


# ---- 目录模式（大单元）支持：按模块收集 / 模块内采样 / 媒体特征原文统计 ----
# 详见 docs/arch/04 §5.5。module_files 形态来自 DirectoryManifestModule.children
# （model_dump 后 [{"name","path","depth","size"}, ...]，path 为相对 output_dir 的路径）。


def _module_rel_paths(module_files: list[dict]) -> list[str]:
    """从 manifest module.children 抽出有效文件相对路径。"""
    rels: list[str] = []
    for mf in module_files or []:
        rel = mf.get("path") or mf.get("name")
        if rel:
            rels.append(str(rel))
    return rels


def collect_module_texts(output_dir: Path, module_files: list[dict]) -> str:
    """合并指定模块（manifest module.children 子集）的文件文本，带 ``=== FILE:`` 标记。

    与 collect_text_content_with_markers 同形态，但只取该模块的文件（而非全目录），
    供 module 粒度评估：每个模块独立喂 LLM，避免整单元塞全文被截断。
    """
    base = Path(output_dir)
    parts: list[str] = []
    for rel in _module_rel_paths(module_files):
        fp = base / rel
        if not fp.is_file():
            continue
        t = file_to_text(fp)
        if t.strip():
            parts.append(f"=== FILE: {rel} ===\n{t}")
    return "\n\n".join(parts)


def _extract_brief(text: str, raw: str, suffix: str) -> str:
    """从单文件抽出简记：标题（首个 #/H 标题）+ 首段（≤500 字符）+ 媒体标记。

    媒体标记对**原文** raw 统计（HTML 标签未被 html_to_text 剥除），修 content_diversity
    对剥标签文本失效的同源问题。
    """
    title_match = re.search(r"^#{1,3}\s+(.+)$", text, re.MULTILINE)
    title = title_match.group(1).strip() if title_match else ""
    body_lines = [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.startswith("#")]
    first_para = body_lines[0][:500] if body_lines else ""
    tags: list[str] = []
    if suffix in (".html", ".htm"):
        if re.search(r"<table", raw, re.I):
            tags.append("[含表格]")
        if re.search(r"<img\s", raw, re.I):
            tags.append("[含图片]")
    if re.findall(r"[$].+?[$]", raw):
        tags.append("[含公式]")
    return "\n".join(p for p in (title, first_para, " ".join(tags)) if p)


def sample_module_brief(
    output_dir: Path, module_files: list[dict], *, max_chars: int = 30000
) -> str:
    """模块内超长兜底：每文件抽标题+首段+媒体标记，拼接 ≤ max_chars 送 LLM。

    当模块合并文本仍超 token 预算时用此函数替代 collect_module_texts，保留模块内
    每个文件的代表性信息（标题/首段/媒体有无），而非简单截断丢后段。
    """
    base = Path(output_dir)
    parts: list[str] = []
    total = 0
    for rel in _module_rel_paths(module_files):
        fp = base / rel
        if not fp.is_file():
            continue
        try:
            raw = fp.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        suffix = fp.suffix.lower()
        text = html_to_text(raw) if suffix in (".html", ".htm") else raw
        brief = _extract_brief(text, raw, suffix)
        if not brief.strip():
            continue
        if total + len(brief) > max_chars:
            remain = max_chars - total
            if remain <= 200:
                break
            brief = brief[:remain] + "\n[...已截断...]"
        parts.append(f"=== FILE: {rel} ===\n{brief}")
        total += len(brief)
        if total >= max_chars:
            break
    return "\n\n".join(parts)


def collect_media_features(output_dir: Path) -> dict[str, str]:
    """对全文件**原文**统计媒体特征，返回 has_formula/has_table/has_image/has_list（是/否）。

    修 content_diversity 的 bug：其对 html_to_text 产物（标签已剥）正则 ``<table``/``<img ``，
    对 HTML 源恒为否。本函数对 HTML 原文统计 table/img，对 Markdown 统计 ``|...|``/``![``。
    """
    has_formula = has_table = has_image = has_list = False
    for f in sorted(Path(output_dir).rglob("*")):
        if not f.is_file() or f.name == "_manifest.json":
            continue
        try:
            raw = f.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if not raw:
            continue
        suffix = f.suffix.lower()
        if suffix in (".html", ".htm"):
            has_table = has_table or bool(re.search(r"<table", raw, re.I))
            has_image = has_image or bool(re.search(r"<img\s", raw, re.I))
        has_formula = has_formula or bool(re.findall(r"[$].+?[$]", raw))
        has_list = (
            has_list
            or bool(re.search(r"^\s*[-*+]\s+", raw, re.MULTILINE))  # markdown 列表
            or bool(re.search(r"<li[>\s]", raw, re.I))  # HTML 列表 <li>
        )
        has_table = has_table or bool(re.search(r"^\|.*\|$", raw, re.MULTILINE))
        has_image = has_image or bool(re.search(r"!\[", raw))
    return {
        "has_formula": "是" if has_formula else "否",
        "has_table": "是" if has_table else "否",
        "has_image": "是" if has_image else "否",
        "has_list": "是" if has_list else "否",
    }
