"""文档截图渲染器 — 将 HTML/Markdown 文档渲染为 PNG 截图。

`ScreenshotRenderer` 是抽象接口，`PlaywrightScreenshotRenderer` 为默认实现
（headless Chromium，full_page 截图）。Markdown 先转 HTML 再渲染。

测试通过注入自定义 `ScreenshotRenderer`（或 mock）避免依赖真实浏览器。
"""

from __future__ import annotations

import base64
from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING

import markdown as md_lib

from agent_eval.config import EVALUATOR_DEFAULTS
from agent_eval.core.exceptions import VisionError

if TYPE_CHECKING:  # playwright 为可选依赖（vision extra），仅类型检查期引入
    from playwright.sync_api import Browser, Playwright

# 内置基础 CSS — 保证不同文档/不同运行间截图可比，含 CJK 字体栈
_BASE_CSS = """
* { box-sizing: border-box; }
body {
    font-family: -apple-system, BlinkMacSystemFont, "PingFang SC",
                 "Microsoft YaHei", "Hiragino Sans GB", "Helvetica Neue",
                 Arial, sans-serif;
    font-size: 16px;
    line-height: 1.7;
    color: #1a1a1a;
    max-width: 900px;
    margin: 24px auto;
    padding: 0 24px;
}
h1, h2, h3, h4 { line-height: 1.3; }
table { border-collapse: collapse; width: 100%; }
th, td { border: 1px solid #ddd; padding: 8px 12px; }
img { max-width: 100%; }
code { background: #f4f4f4; padding: 2px 4px; border-radius: 3px; }
pre { background: #f4f4f4; padding: 12px; border-radius: 6px; overflow-x: auto; }
"""

# Chromium 启动参数 — 容器/SCF 适配（本地同样安全：仅在无对应资源时无害降级）。
# --disable-dev-shm-usage 是关键：容器 /dev/shm 通常仅 64MB，full_page 截整页 PNG 会撑爆
# 共享内存致渲染挂起、超过 screenshot 默认 30s 超时；改用 /tmp 作共享内存规避。
_CHROMIUM_LAUNCH_ARGS = [
    "--no-sandbox",  # SCF/容器 root 运行，无 sandbox 命名空间
    "--disable-dev-shm-usage",  # 改用 /tmp，规避容器共享内存不足
    "--disable-gpu",  # 无 GPU 环境
]


def _markdown_to_html(md_text: str) -> str:
    """Markdown 转 HTML（套内置 CSS）。"""
    body = md_lib.markdown(md_text, extensions=["extra", "tables", "fenced_code"])
    return (
        "<html><head><meta charset='utf-8'>"
        f"<style>{_BASE_CSS}</style></head><body>{body}</body></html>"
    )


def png_to_data_uri(png_path: Path) -> str:
    """读取 PNG 文件并编码为 data URI（供 chat_with_vision 使用）。"""
    data = Path(png_path).read_bytes()
    b64 = base64.b64encode(data).decode("ascii")
    return f"data:image/png;base64,{b64}"


class ScreenshotRenderer(ABC):
    """文档截图渲染器抽象基类。"""

    @abstractmethod
    def render(
        self,
        sources: list[Path],
        *,
        out_dir: Path,
        viewport: tuple[int, int] = (1280, 800),
    ) -> list[Path]:
        """将每个源文档渲染为一张 PNG 截图（full_page）。

        Args:
            sources: 源文档路径列表（.md/.markdown/.html/.htm）。
            out_dir: 截图输出目录。
            viewport: 视口尺寸（宽, 高）。

        Returns:
            生成的 PNG 路径列表（与 sources 一一对应）。

        Raises:
            VisionError: 渲染失败（依赖缺失、浏览器不可用等）。
        """
        ...

    def close(self) -> None:
        """释放资源（如浏览器进程）。默认无操作，子类按需覆盖。"""

    def __enter__(self) -> ScreenshotRenderer:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


class PlaywrightScreenshotRenderer(ScreenshotRenderer):
    """基于 Playwright headless Chromium 的截图渲染器。

    playwright 在方法内懒导入；浏览器进程在首次 render 时启动，close() 时释放。
    建议作为上下文管理器使用（`with PlaywrightScreenshotRenderer() as r: ...`）。
    """

    def __init__(self) -> None:
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None

    def _ensure_browser(self) -> Browser:
        """懒启动 playwright 与浏览器，返回 browser 实例。"""
        if self._browser is not None:
            return self._browser

        try:
            from playwright.sync_api import sync_playwright
        except ImportError as e:
            raise VisionError(
                "playwright 库未安装。请执行: uv sync --extra vision",
                details={"missing_module": "playwright"},
            ) from e

        try:
            self._playwright = sync_playwright().start()
            self._browser = self._playwright.chromium.launch(
                headless=True,
                args=_CHROMIUM_LAUNCH_ARGS,
            )
        except Exception as e:
            # 最常见原因：浏览器二进制未下载
            raise VisionError(
                "Chromium 启动失败，可能未下载浏览器。请执行: playwright install chromium",
                details={"original_error": str(e)},
            ) from e
        return self._browser

    def render(
        self,
        sources: list[Path],
        *,
        out_dir: Path,
        viewport: tuple[int, int] = (1280, 800),
    ) -> list[Path]:
        """渲染每个源文档为一张 full_page PNG 截图。"""
        if not sources:
            return []

        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        browser = self._ensure_browser()

        results: list[Path] = []
        for i, src in enumerate(sources):
            src = Path(src)
            png_path = out_dir / f"{src.stem}_{i:03d}.png"
            page = browser.new_page(viewport={"width": viewport[0], "height": viewport[1]})
            try:
                if src.suffix.lower() in (".md", ".markdown"):
                    html = _markdown_to_html(src.read_text(encoding="utf-8"))
                    page.set_content(html, wait_until="domcontentloaded")
                else:
                    # domcontentloaded：不等外部图片/字体等资源，避免无外网的 SCF 环境卡在 load。
                    page.goto(src.resolve().as_uri(), wait_until="domcontentloaded")
                page.screenshot(
                    path=str(png_path),
                    full_page=True,
                    timeout=EVALUATOR_DEFAULTS.vision_screenshot_timeout_ms,
                    animations="disabled",  # 冻结 CSS/JS 动画，避免 full_page 等待动画稳定
                )
            except Exception as e:
                raise VisionError(
                    f"渲染截图失败: {src}: {e}",
                    details={"source": str(src)},
                ) from e
            finally:
                page.close()
            results.append(png_path)
        return results

    def close(self) -> None:
        """关闭浏览器与 playwright。"""
        if self._browser is not None:
            try:
                self._browser.close()
            except Exception:
                pass
            self._browser = None
        if self._playwright is not None:
            try:
                self._playwright.stop()
            except Exception:
                pass
            self._playwright = None
