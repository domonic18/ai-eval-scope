"""工作台欢迎首屏富渲染——开源 CLI 风格渐变 logo 横幅。

表现层专属：ASCII wordmark（ANSI Shadow 字形，零依赖）+ 竖直渐变色带 + 分区配色
（身份与 slogan / 元信息 / 使用示例 / 红线与控制 / 版本与主页脚注）。文案仍是资产
真相源——prompts.yaml ``banner:`` 结构化段经 ``WorkbenchAgent.banner_data`` 注入，
CLI 只渲染不写死；对标 Gemini CLI（渐变 logo）与 Claude Code（slogan 直入对话）。
"""

from __future__ import annotations

from typing import Any

from rich import print as rprint
from rich.cells import cell_len
from rich.console import Console
from rich.text import Text

__all__ = ["render_banner"]

# ANSI Shadow 字形（每字母行内等宽，字距由字形自带 padding 决定——密集相接是该
# 字体的标志性形态，词间才显式留白）。新增字母须保证 6 行且行宽一致。
_GLYPHS: dict[str, list[str]] = {
    "A": [" █████╗ ", "██╔══██╗", "███████║", "██╔══██║", "██║  ██║", "╚═╝  ╚═╝"],
    "E": ["███████╗", "██╔════╝", "█████╗  ", "██╔══╝  ", "███████╗", "╚══════╝"],
    "G": [" ██████╗ ", "██╔════╝ ", "██║  ███╗", "██║   ██║", "╚██████╔╝", " ╚═════╝ "],
    "L": ["██╗     ", "██║     ", "██║     ", "██║     ", "███████╗", "╚══════╝"],
    "N": ["███╗   ██╗", "████╗  ██║", "██╔██╗ ██║", "██║╚██╗██║", "██║ ╚████║", "╚═╝  ╚═══╝"],
    "T": ["████████╗", "╚══██╔══╝", "   ██║   ", "   ██║   ", "   ██║   ", "   ╚═╝   "],
    "V": ["██╗   ██╗", "██║   ██║", "██║   ██║", "╚██╗ ██╔╝", " ╚████╔╝ ", "  ╚═══╝  "],
}
_WORD_GAP = 3  # 词间留白列数
_INDENT = "  "
_MAX_WIDTH = 100  # 横幅不拉满超宽终端（CJK 双宽截断防护）

# 竖直渐变色带：青 → 蓝 → 紫 → 洋红（深/浅色终端背景均可读）
_RAMP: tuple[str, ...] = ("#00D7FF", "#3FA9FF", "#7B6FFF", "#A95FFF", "#D75FFF", "#FF5FD7")
_DOMAIN_COLORS: tuple[str, ...] = ("cyan", "green", "magenta", "yellow", "#7B6FFF")
_EXAMPLE_COLORS: tuple[str, ...] = ("#5FD7FF", "#5FFF87", "#FF5FD7", "#FFD75F", "#9D7BFF")


def _assemble_logo() -> tuple[str, ...]:
    """wordmark 六行：字母零间隔拼装（padding 自带），词间留白。"""

    def _word(letters: str) -> list[str]:
        return ["".join(_GLYPHS[c][i] for c in letters) for i in range(6)]

    left, right = _word("AGENT"), _word("EVAL")
    return tuple((lft + " " * _WORD_GAP + rgt).rstrip() for lft, rgt in zip(left, right))


_LOGO: tuple[str, ...] = _assemble_logo()
_LOGO_COLS = max(len(row) for row in _LOGO)


def _logo_text(width: int) -> Text | None:
    """渐变 wordmark；终端放不下返回 None（调用方降级单行 wordmark）。"""
    if width < _LOGO_COLS + 4:
        return None
    band = _LOGO_COLS / len(_RAMP)
    text = Text()
    for row in _LOGO:
        text.append(_INDENT)
        for i, color in enumerate(_RAMP):
            text.append(row[int(i * band) : int((i + 1) * band)], style=color)
        text.append("\n")
    return text


def _wordmark_text() -> Text:
    """窄终端降级：单行逐字渐变 wordmark。"""
    label = "AGENT EVAL"
    text = Text(_INDENT)
    for i, ch in enumerate(label):
        idx = min(i * len(_RAMP) // len(label), len(_RAMP) - 1)
        text.append(ch, style=f"bold {_RAMP[idx]}")
    return text


def _domain_text(label: str) -> Text:
    """能力域按「·」分段轮换配色；尾注（（其余域…））压暗。"""
    text = Text()
    segments = label.split("·")
    for i, seg in enumerate(segments):
        head, sep, tail = seg.partition("（")
        text.append(head, style=_DOMAIN_COLORS[i % len(_DOMAIN_COLORS)])
        if sep:
            text.append(sep + tail, style="dim")
        if i < len(segments) - 1:
            text.append("·", style="dim")
    return text


def _example_text(example: str, color: str) -> Text:
    """示例条目：▸ 彩色子弹 + 需求话术，「——」后的解释压暗。"""
    utterance, sep, note = example.partition("——")
    text = Text(f"{_INDENT}▸ ", style=color)
    text.append(utterance)
    if sep:
        text.append(f"——{note}", style="dim")
    return text


def _footer_text(parts: dict[str, Any], version: str, width: int) -> Text:
    """版本 + 主页脚注（右对齐；主页带终端超链接，不支持超链接的终端原样显示）。"""
    footer = Text(f"v{version}", style="dim")
    home = str(parts.get("homepage") or "").strip()
    if home:
        footer.append(" · ", style="dim")
        footer.append(home.removeprefix("https://"), style=f"dim link {home}")
    pad = max(0, width - cell_len(footer.plain) - 1)
    return Text("\n" + " " * pad).append_text(footer)


def render_banner(parts: dict[str, Any], version: str) -> None:
    """欢迎首屏：渐变 logo + 身份/slogan + 元信息 + 示例 + 红线 + 脚注。

    ``parts``（``banner_parts`` 产物）为空时静默返回——资产缺 banner 段即无横幅。
    """
    if not parts:
        return
    width = min(Console().width or _MAX_WIDTH, _MAX_WIDTH)
    out = Text()
    logo = _logo_text(width)
    if logo is not None:
        out.append_text(logo)
    else:
        out.append_text(_wordmark_text())
    out.append("\n\n")
    # 身份 + slogan
    out.append("✦ ", style="bold cyan")
    out.append(str(parts["identity"]), style="bold")
    out.append(" —— ", style="dim")
    out.append(str(parts["slogan"]), style="italic #FF5FD7")
    out.append("\n\n")
    # 元信息：任务对象 / 能力域（标签列对齐 = ◆ + 6/5 字标签 + 补位空格）
    out.append(f"{_INDENT}◆ 当前任务对象  ", style="cyan")
    out.append(str(parts["root"]) + "\n", style="dim")
    out.append(f"{_INDENT}◆ 可用能力域    ", style="cyan")
    out.append_text(_domain_text(str(parts["domains"])))
    out.append("\n\n")
    # 使用示例
    out.append(f"{_INDENT}{parts['examples_label']}：\n", style="bold")
    for i, example in enumerate(parts.get("examples") or ()):
        color = _EXAMPLE_COLORS[i % len(_EXAMPLE_COLORS)]
        out.append_text(_example_text(str(example), color))
        out.append("\n")
    out.append("\n")
    # 红线与控制
    out.append(f"{_INDENT}◆ ", style="yellow")
    out.append("规则  ", style="bold yellow")
    out.append(str(parts["rules"]) + "\n", style="dim")
    out.append(f"{_INDENT}◆ ", style="cyan")
    out.append("控制  ", style="bold cyan")
    out.append(str(parts["control"]) + "\n", style="dim")
    out.append_text(_footer_text(parts, version, width))
    rprint(out)
