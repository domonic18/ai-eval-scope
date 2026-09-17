"""流式 markdown-lite 渲染 — 行粒度轻量转换（表现层基础设施，无业务语义）。

逐 token 流式与 markdown 解析天然冲突：token 到达时语法不完整，无法边收边解析；
全量重渲染（rich Live + Markdown）对长回复是 O(n²) 且与工具行直播抢终端——
故取行缓冲折中：完整行到达才转换，部分行挂起至收行兜底（调度在 agent_stream）。

保守规则集：标题 / 粗体 / 行内代码 / 列表符号（含任务框）/ 删除线 / 引用 /
分割线 / 围栏。单星斜体、表格对齐不做——模型字面量误伤不可控且视觉收益小；
围栏内逐字直写（代码保真）。用 rich ``Text``+span 而非 markup 字符串构建：
模型文本可能含 ``[``，markup 有注入面。
"""

from __future__ import annotations

import re

from rich.text import Text

_FENCE = re.compile(r"^\s*(`{3,}|~{3,})")
_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_HR = re.compile(r"^\s{0,3}(?:-{3,}|\*{3,}|_{3,})\s*$")
_QUOTE = re.compile(r"^\s*> ?(.*)$")
_BULLET = re.compile(r"^(\s*)[-*+]\s+(.*)$")
_ORDERED = re.compile(r"^(\s*)(\d+)([.)])\s+(.*)$")
_TASK = re.compile(r"^\[( |x|X)\] (.*)$")

# 内联规则一次扫描：代码优先（代码内的 ** 不再当粗体），其后粗体 / 删除线 / 链接
_INLINE = re.compile(
    r"`(?P<code>[^`]+)`"
    r"|\*\*(?P<bold>[^*]+?)\*\*"
    r"|~~(?P<strike>[^~]+?)~~"
    r"|\[(?P<link_text>[^\]]*)\]\((?P<link_url>[^)\s]*)\)"
)

_INLINE_STYLE: dict[str, str] = {"code": "bold cyan", "bold": "bold", "strike": "strike"}


class MarkdownLite:
    """有状态的行转换器：跨行状态仅围栏。``feed_line`` 收不含行尾换行的完整行。"""

    def __init__(self) -> None:
        self._fence = ""  # 非空 = 围栏内，值为围栏标记（如 ```python 的 ```）

    def feed_line(self, line: str) -> Text:
        """一行完整文本 → 带样式的 Text（不改原文内容，仅加样式 / 换符号）。"""
        fence = _FENCE.match(line)
        if fence:
            marker = fence.group(1)
            if self._fence:
                if marker[0] == self._fence[0]:  # 同字符围栏闭合（```…``` / ~~~…~~~）
                    self._fence = ""
                    return Text(line, style="dim")
            else:
                self._fence = marker
                return Text(line, style="dim")
            return Text(line)  # 异构围栏标记在围栏内出现——按代码内容处理
        if self._fence:
            return Text(line)  # 围栏内逐字直写：代码保真，不做内联转换
        if _HR.match(line):
            return Text(line, style="dim")
        m = _HEADING.match(line)
        if m:
            return Text(m.group(2), style="bold cyan")
        m = _QUOTE.match(line)
        if m:
            inner = _inline(m.group(1))
            inner.stylize("italic", 0, len(inner))
            out = Text("▎ ", style="dim")
            out.append(inner)
            return out
        m = _BULLET.match(line)
        if m:
            return _bullet(m.group(1), m.group(2))
        m = _ORDERED.match(line)
        if m:
            out = Text(m.group(1))
            out.append(f"{m.group(2)}. ", style="bold cyan")
            out.append(_inline(m.group(4)))
            return out
        return _inline(line)


def _bullet(indent: str, rest: str) -> Text:
    """无序列表行：任务框（- [ ] / - [x]）转 ○/✓，普通项转 •。"""
    m = _TASK.match(rest)
    if m:
        done = m.group(1).lower() == "x"
        inner = _inline(m.group(2))
        if done:
            inner.stylize("dim strike", 0, len(inner))
        out = Text(indent)
        out.append("✓ " if done else "○ ", style="green" if done else "cyan")
        out.append(inner)
        return out
    out = Text(indent)
    out.append("• ", style="bold cyan")
    out.append(_inline(rest))
    return out


def _inline(text: str) -> Text:
    """行内规则：`` `code` `` / ``**bold**`` / ``~~strike~~`` / 链接；其余原样。"""
    out = Text()
    pos = 0
    for m in _INLINE.finditer(text):
        if m.start() > pos:
            out.append(text[pos : m.start()])
        if m.group("link_text") is not None:
            # 链接：文本下划线着色，URL 弱化附注（信息不丢）
            out.append(m.group("link_text"), style="underline cyan")
            out.append(f" ({m.group('link_url')})", style="dim")
        else:
            kind = (
                "code"
                if m.group("code") is not None
                else ("bold" if m.group("bold") is not None else "strike")
            )
            out.append(m.group(kind), style=_INLINE_STYLE[kind])
        pos = m.end()
    if pos < len(text):
        out.append(text[pos:])
    return out
