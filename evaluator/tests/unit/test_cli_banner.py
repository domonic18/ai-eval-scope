"""cli/console/banner 富渲染横幅单测。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from agent_eval.agent.workbench.agent import WorkbenchAgent
from agent_eval.cli.console.banner import (
    _LOGO,
    _domain_text,
    _example_text,
    _footer_text,
    _logo_text,
    _wordmark_text,
    render_banner,
)

_PARTS: dict[str, Any] = {
    "identity": "agent-eval 工作台 Agent",
    "slogan": "把评测工程，交给一句自然语言",
    "homepage": "https://github.com/domonic18/ai-eval-scope",
    "examples_label": "可以这样用我",
    "examples": ["「下载 gsm8k」——先查索引", "「跑评测」"],
    "rules": "先进暂存区",
    "control": "Ctrl+C 暂停",
    "root": "/tmp/pkg",
    "domains": "场景包工程 · 评测执行 · 数据集下载（其余域随版本增装）",
}


def test_logo_shape_and_size() -> None:
    # 六行 wordmark；最宽行落在 100 列横幅内（窄终端另有单行降级）
    assert len(_LOGO) == 6
    assert max(len(row) for row in _LOGO) <= 84
    assert _LOGO[0].startswith(" █████╗")  # 字形首行形态抽查


def test_logo_gradient_multi_style() -> None:
    text = _logo_text(100)
    assert text is not None
    styles = {span.style for span in text.spans}
    assert {"#00D7FF", "#FF5FD7"} <= styles  # 渐变首尾色带均出现
    assert _logo_text(50) is None  # 终端放不下 → 调用方降级单行 wordmark


def test_wordmark_gradient() -> None:
    text = _wordmark_text()
    assert text.plain.strip() == "AGENT EVAL"
    assert len({span.style for span in text.spans}) >= 3  # 逐字渐变


def test_domain_text_colors_and_dim() -> None:
    label = "场景包工程 · 评测执行 · 数据集下载（其余域随版本增装）"
    text = _domain_text(label)
    assert text.plain == label  # 纯内容不变，配色只是样式
    styles = {span.style for span in text.spans}
    assert "dim" in styles  # 尾注压暗
    assert len(styles) >= 3  # 分段轮换配色


def test_example_text_dims_note() -> None:
    text = _example_text("「下载 gsm8k」——先查索引", "#5FD7FF")
    assert text.plain == "  ▸ 「下载 gsm8k」——先查索引"
    assert "dim" in {span.style for span in text.spans}  # ——解释压暗


def test_footer_version_and_homepage() -> None:
    text = _footer_text(_PARTS, "9.9.9", 100)
    assert text.plain.endswith("v9.9.9 · github.com/domonic18/ai-eval-scope")
    assert any(span.style and "link" in str(span.style) for span in text.spans)  # 超链接
    assert _footer_text({"homepage": ""}, "1.0.0", 100).plain.strip() == "v1.0.0"  # 无主页


def test_render_banner_smoke(capsys) -> None:
    render_banner(_PARTS, "9.9.9")
    out = capsys.readouterr().out
    assert "AGENT EVAL" in out and "把评测工程" in out
    assert "✦" in out and "▸" in out
    assert "v9.9.9" in out


def test_render_banner_empty_parts_silent(capsys) -> None:
    # 资产缺 banner 段 → parts 为空 → 无横幅
    render_banner({}, "9.9.9")
    assert capsys.readouterr().out == ""


def test_render_banner_narrow_degrades(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setenv("COLUMNS", "60")
    render_banner(_PARTS, "9.9.9")
    out = capsys.readouterr().out
    assert "AGENT EVAL" in out  # 单行 wordmark 形态
    assert "█████╗" not in out  # 盒线 logo 不出现


def test_banner_data_feeds_render(tmp_path: Path, capsys) -> None:
    # 资产 → banner_data → render_banner 全链路（文案真相源在 yaml 资产）
    agent = WorkbenchAgent(tmp_path, log_dir=tmp_path / "log")
    render_banner(agent.banner_data(), "9.9.9")
    out = capsys.readouterr().out
    assert "工作台 Agent" in out and "github.com/domonic18" in out
    assert "暂存" in out and "Ctrl+C" in out  # 红线与控制随资产注入
