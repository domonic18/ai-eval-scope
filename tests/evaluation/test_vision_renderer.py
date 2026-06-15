"""ScreenshotRenderer / PlaywrightScreenshotRenderer Mock 测试。"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agent_eval.core.exceptions import VisionError


class _FakePage:
    """假 Page：记录 set_content/goto/screenshot 调用。"""

    def __init__(self, browser) -> None:
        self._browser = browser
        self.content_set = None
        self.goto_url = None
        self.screenshot_path = None

    def set_content(self, html, **kw):
        self.content_set = html

    def goto(self, url, **kw):
        self.goto_url = url

    def screenshot(self, *, path, **kw):
        self.screenshot_path = path
        # 写一个占位 PNG 字节
        Path(path).write_bytes(b"\x89PNG\r\n\x1a\nfake")

    def close(self):
        pass


class _FakeBrowser:
    def __init__(self) -> None:
        self.pages: list[_FakePage] = []

    def new_page(self, **kw):
        p = _FakePage(self)
        self.pages.append(p)
        return p

    def close(self):
        pass


class _FakePlaywright:
    def __init__(self) -> None:
        self._browser = _FakeBrowser()

    @property
    def chromium(self):
        outer = self

        class _Chromium:
            def launch(self):
                return outer._browser

        return _Chromium()

    def stop(self):
        pass


class _FakePlaywrightStarter:
    """模拟 sync_playwright() 的返回值：调用 .start() 返回 playwright 实例。"""

    def start(self) -> _FakePlaywright:
        return _FakePlaywright()


def _fake_sync_playwright():
    return _FakePlaywrightStarter()


class TestPlaywrightScreenshotRenderer:
    """PlaywrightScreenshotRenderer 测试（Mock playwright）。"""

    def test_render_markdown(self, tmp_path: Path) -> None:
        """Markdown 文档渲染为 PNG（先转 HTML）。"""
        md_file = tmp_path / "doc.md"
        md_file.write_text("# 标题\n\n正文内容", encoding="utf-8")

        fake_module = MagicMock()
        fake_module.sync_playwright = _fake_sync_playwright

        with patch.dict(sys.modules, {"playwright.sync_api": fake_module}):
            from agent_eval.evaluation.vision.renderer import (
                PlaywrightScreenshotRenderer,
            )

            with PlaywrightScreenshotRenderer() as r:
                out = tmp_path / "shots"
                results = r.render([md_file], out_dir=out)

        assert len(results) == 1
        assert results[0].exists()
        assert results[0].suffix == ".png"

    def test_render_html(self, tmp_path: Path) -> None:
        """HTML 文档直接 goto 渲染。"""
        html_file = tmp_path / "page.html"
        html_file.write_text("<html><body><h1>Hi</h1></body></html>", encoding="utf-8")

        fake_module = MagicMock()
        fake_module.sync_playwright = _fake_sync_playwright

        with patch.dict(sys.modules, {"playwright.sync_api": fake_module}):
            from agent_eval.evaluation.vision.renderer import (
                PlaywrightScreenshotRenderer,
            )

            r = PlaywrightScreenshotRenderer()
            results = r.render([html_file], out_dir=tmp_path / "out")
            r.close()

        assert len(results) == 1

    def test_playwright_not_installed(self, tmp_path: Path) -> None:
        """playwright 未安装时抛 VisionError 含安装提示。"""
        md_file = tmp_path / "doc.md"
        md_file.write_text("# x", encoding="utf-8")

        # 移除已加载的 renderer 与 playwright 模块，强制重导入触发 ImportError
        import importlib

        real_sync_api = sys.modules.get("playwright.sync_api")
        sys.modules["playwright.sync_api"] = None  # 触发 ImportError
        try:
            from agent_eval.evaluation.vision.renderer import (
                PlaywrightScreenshotRenderer,
            )

            r = PlaywrightScreenshotRenderer()
            with pytest.raises(VisionError, match="playwright"):
                r.render([md_file], out_dir=tmp_path / "out")
            r.close()
        finally:
            if real_sync_api is not None:
                sys.modules["playwright.sync_api"] = real_sync_api
            else:
                sys.modules.pop("playwright.sync_api", None)
            importlib.import_module("agent_eval.evaluation.vision.renderer")

    def test_close_without_browser_is_noop(self) -> None:
        """未启动浏览器时 close() 不报错。"""
        from agent_eval.evaluation.vision.renderer import (
            PlaywrightScreenshotRenderer,
        )

        r = PlaywrightScreenshotRenderer()
        r.close()  # 不应抛异常
        r.close()  # 幂等


class TestHelpers:
    """模块级辅助函数测试。"""

    def test_png_to_data_uri(self, tmp_path: Path) -> None:
        """PNG → data URI 编码。"""
        png = tmp_path / "x.png"
        png.write_bytes(b"abc")
        from agent_eval.evaluation.vision.renderer import png_to_data_uri

        uri = png_to_data_uri(png)
        assert uri.startswith("data:image/png;base64,")
        assert "abc" not in uri  # 已 base64 编码

    def test_markdown_to_html_has_style(self) -> None:
        """Markdown → HTML 含内置 CSS 与正文。"""
        from agent_eval.evaluation.vision.renderer import _markdown_to_html

        html = _markdown_to_html("# 标题\n\n**粗**")
        assert "<style>" in html
        assert "<h1>" in html
        assert "<strong>" in html
