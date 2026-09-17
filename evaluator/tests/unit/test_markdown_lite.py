"""markdown-lite 行转换单测 — 流式正文的终端可读性（arch/15 §六）。

纯函数级验证：规则命中 / 围栏保真 / 注入面 / 未配对标记不误伤。
"""

from __future__ import annotations

from agent_eval.cli.console.markdown_lite import MarkdownLite


def _plain(md: MarkdownLite, line: str) -> str:
    return md.feed_line(line).plain


def _styles(md: MarkdownLite, line: str) -> list[str]:
    return [s.style for s in md.feed_line(line).spans]


class TestBlockRules:
    def test_heading_strips_hashes_and_bolds(self) -> None:
        md = MarkdownLite()
        t = md.feed_line("## 执行摘要")
        assert t.plain == "执行摘要"
        assert t.style == "bold cyan"

    def test_heading_with_trailing_hashes(self) -> None:
        md = MarkdownLite()
        assert _plain(md, "### 小节 ###") == "小节"

    def test_bullet_becomes_dot(self) -> None:
        md = MarkdownLite()
        assert _plain(md, "- 第一步") == "• 第一步"
        assert "bold cyan" in _styles(md, "- 第一步")

    def test_task_list_boxes(self) -> None:
        md = MarkdownLite()
        assert _plain(md, "- [ ] 待办") == "○ 待办"
        assert _plain(md, "- [x] 已完") == "✓ 已完"
        # 完成项整段弱化（删除线 span 覆盖内容）
        assert "dim strike" in _styles(md, "- [x] 已完")

    def test_ordered_list_keeps_number(self) -> None:
        md = MarkdownLite()
        assert _plain(md, "1. 有序步骤") == "1. 有序步骤"

    def test_blockquote_prefix(self) -> None:
        md = MarkdownLite()
        assert _plain(md, "> 引用") == "▎ 引用"
        assert "italic" in _styles(md, "> 引用")

    def test_horizontal_rule_dimmed_verbatim(self) -> None:
        md = MarkdownLite()
        assert _plain(md, "---") == "---"
        assert md.feed_line("---").style == "dim"


class TestInlineRules:
    def test_bold_span(self) -> None:
        md = MarkdownLite()
        t = md.feed_line("a **粗** c")
        assert t.plain == "a 粗 c"
        assert any(s.style == "bold" and t.plain[s.start : s.end] == "粗" for s in t.spans)

    def test_inline_code_span(self) -> None:
        md = MarkdownLite()
        t = md.feed_line("收到 `{}` 字符串")
        assert t.plain == "收到 {} 字符串"
        assert any(s.style == "bold cyan" and t.plain[s.start : s.end] == "{}" for s in t.spans)

    def test_strike_span(self) -> None:
        md = MarkdownLite()
        t = md.feed_line("~~废弃~~保留")
        assert t.plain == "废弃保留"
        assert any(s.style == "strike" and t.plain[s.start : s.end] == "废弃" for s in t.spans)

    def test_link_text_plus_dim_url(self) -> None:
        md = MarkdownLite()
        t = md.feed_line("见 [文档](https://e.com) 说明")
        assert t.plain == "见 文档 (https://e.com) 说明"
        assert any(t.plain[s.start : s.end] == "文档" for s in t.spans)

    def test_unpaired_markers_untouched(self) -> None:
        md = MarkdownLite()
        assert _plain(md, "未配对 ** 粗体") == "未配对 ** 粗体"
        assert md.feed_line("未配对 ** 粗体").spans == []

    def test_bracket_literal_no_markup_injection(self) -> None:
        """模型字面量 ``[`` 不经 markup 解析——Text 构建天然免疫。"""
        md = MarkdownLite()
        assert _plain(md, "表格 | 原样 | [风险标记]") == "表格 | 原样 | [风险标记]"


class TestFence:
    def test_fence_content_verbatim(self) -> None:
        md = MarkdownLite()
        assert md.feed_line("```python").style == "dim"  # 开栏弱化
        t = md.feed_line('print("a **b** c")')
        assert t.plain == 'print("a **b** c")'
        assert t.spans == []  # 围栏内零转换（代码保真）

    def test_fence_close_reenables_rules(self) -> None:
        md = MarkdownLite()
        md.feed_line("```")
        md.feed_line("code **x**")
        assert md.feed_line("```").style == "dim"  # 闭栏弱化
        assert md.feed_line("**恢复**").spans != []  # 栏后规则恢复

    def test_tilde_fence_roundtrip(self) -> None:
        md = MarkdownLite()
        md.feed_line("~~~")
        assert md.feed_line("```) 异构标记按内容处理").spans == []
        md.feed_line("~~~")
        assert md.feed_line("- 重新生效").plain == "• 重新生效"
