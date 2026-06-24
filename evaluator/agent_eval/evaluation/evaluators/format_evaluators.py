"""格式约束评估器（2 项）— HARD_GATE。

- format.response_format: 文件格式检查（MD/HTML）
- format.html_validity: HTML 标签有效性
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from agent_eval.config import EVALUATOR_DEFAULTS
from agent_eval.core.types import ConstraintTier, EvalMethod, EvalStatus
from agent_eval.evaluation.base import BaseEvaluator
from agent_eval.evaluation.registry import registry


@registry.register("format.response_format")
class ResponseFormatEvaluator(BaseEvaluator):
    """文件格式检查 — 验证输出文件为有效的 Markdown 或 HTML。"""

    evaluator_id = "format.response_format"
    name = "文件格式检查"
    tier = ConstraintTier.HARD_GATE
    method = EvalMethod.RULE

    # 已知的有效格式
    VALID_EXTENSIONS = {".md", ".markdown", ".html", ".htm"}

    def evaluate(self, sample: Any, context: dict[str, Any]) -> Any:
        import time

        start = time.monotonic()
        allowed = set(self.params.get("allowed_formats", EVALUATOR_DEFAULTS.allowed_formats))
        allowed_exts = set()
        for fmt in allowed:
            fmt = fmt.lower().strip(".")
            allowed_exts.add(f".{fmt}")
            if fmt == "markdown":
                allowed_exts.add(".md")
                allowed_exts.add(".markdown")
            elif fmt == "html":
                allowed_exts.add(".html")
                allowed_exts.add(".htm")

        output_dir = self._get_output_dir(sample)
        if output_dir is None or not output_dir.exists():
            return self._make_result(
                status=EvalStatus.FAIL,
                score=0.0,
                reason="输出目录不存在",
                duration_ms=self._elapsed_ms(start),
            )

        # 收集所有输出文件（跳过 _manifest.json）
        files = [f for f in output_dir.rglob("*") if f.is_file() and f.name != "_manifest.json"]

        if not files:
            return self._make_result(
                status=EvalStatus.FAIL,
                score=0.0,
                reason="输出目录中无文件",
                duration_ms=self._elapsed_ms(start),
            )

        invalid_files = []
        valid_count = 0
        for f in files:
            ext = f.suffix.lower()
            if ext in allowed_exts:
                # 内容头校验
                if self._check_content_header(f, ext):
                    valid_count += 1
                else:
                    invalid_files.append(f"{f.name} (内容与扩展名不匹配)")
            else:
                invalid_files.append(f"{f.name} (不支持的格式: {ext})")

        elapsed = self._elapsed_ms(start)

        if not invalid_files:
            return self._make_result(
                status=EvalStatus.PASS,
                score=1.0,
                reason=f"全部 {valid_count} 个文件格式有效",
                details={
                    "checked_files": [f.name for f in files],
                    "valid_formats": sorted(allowed_exts),
                    "total": len(files),
                    "valid_count": valid_count,
                },
                duration_ms=elapsed,
            )
        else:
            return self._make_result(
                status=EvalStatus.FAIL,
                score=0.0,
                reason=f"格式不合规: {'; '.join(invalid_files[:5])}",
                details={
                    "invalid_files": invalid_files,
                    "checked_files": [f.name for f in files],
                    "valid_count": valid_count,
                    "total": len(files),
                },
                duration_ms=elapsed,
            )

    def _check_content_header(self, filepath: Path, ext: str) -> bool:
        """检查文件内容头是否与扩展名一致。"""
        try:
            content = filepath.read_text(encoding="utf-8", errors="ignore")[:500]
        except OSError:
            return False

        if ext in (".md", ".markdown"):
            # Markdown 文件应包含标题、列表或普通文本
            stripped = content.strip()
            if not stripped:
                return False
            return True
        elif ext in (".html", ".htm"):
            stripped = content.strip().lower()
            return stripped.startswith("<") or "<!doctype" in stripped or "<html" in stripped
        return True

    def _get_output_dir(self, sample: Any) -> Path | None:
        """从样本中提取 output 目录。"""
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

    def _elapsed_ms(self, start: float) -> float:
        import time

        return (time.monotonic() - start) * 1000


@registry.register("format.html_validity")
class HtmlValidityEvaluator(BaseEvaluator):
    """HTML 有效性检查 — 验证 HTML 标签闭合、可正常解析。"""

    evaluator_id = "format.html_validity"
    name = "HTML 有效性检查"
    tier = ConstraintTier.HARD_GATE
    method = EvalMethod.RULE

    def evaluate(self, sample: Any, context: dict[str, Any]) -> Any:
        import time

        start = time.monotonic()
        check_html_only = self.params.get("check_html_only", True)

        output_dir = self._get_output_dir(sample)
        if output_dir is None or not output_dir.exists():
            elapsed = (time.monotonic() - start) * 1000
            return self._make_result(
                status=EvalStatus.FAIL,
                score=0.0,
                reason="输出目录不存在",
                duration_ms=elapsed,
            )

        html_files = list(output_dir.rglob("*.html")) + list(output_dir.rglob("*.htm"))

        if check_html_only and not html_files:
            # 没有 HTML 文件时自动通过（仅检查 HTML）
            elapsed = (time.monotonic() - start) * 1000
            return self._make_result(
                status=EvalStatus.PASS,
                score=1.0,
                reason="无 HTML 文件，跳过检查",
                duration_ms=elapsed,
            )

        if not html_files:
            elapsed = (time.monotonic() - start) * 1000
            return self._make_result(
                status=EvalStatus.PASS,
                score=1.0,
                reason="无 HTML 文件需要检查",
                duration_ms=elapsed,
            )

        issues: list[str] = []
        valid_count = 0

        for f in html_files:
            try:
                content = f.read_text(encoding="utf-8", errors="ignore")
            except OSError as e:
                issues.append(f"{f.name}: 读取失败 — {e}")
                continue

            result = self._validate_html(content, f.name)
            if result["valid"]:
                valid_count += 1
            else:
                issues.extend(result["errors"])

        elapsed = (time.monotonic() - start) * 1000

        if not issues:
            return self._make_result(
                status=EvalStatus.PASS,
                score=1.0,
                reason=f"全部 {valid_count} 个 HTML 文件有效",
                details={"valid_files": [f.name for f in html_files], "total": len(html_files)},
                duration_ms=elapsed,
            )
        else:
            return self._make_result(
                status=EvalStatus.FAIL,
                score=0.0,
                reason=f"HTML 校验失败: {'; '.join(issues[:5])}",
                details={
                    "issues": issues,
                    "valid_count": valid_count,
                    "total": len(html_files),
                    "checked_files": [f.name for f in html_files],
                },
                duration_ms=elapsed,
            )

    def _validate_html(self, content: str, filename: str) -> dict[str, Any]:
        """校验 HTML 内容基本有效性。"""
        errors: list[str] = []

        # 检查是否为空
        stripped = content.strip()
        if not stripped:
            errors.append(f"{filename}: 文件为空")
            return {"valid": False, "errors": errors}

        # 检查是否有基本的 HTML 结构
        lower = stripped.lower()
        if not (lower.startswith("<") or "<!doctype" in lower or "<html" in lower):
            errors.append(f"{filename}: 不包含 HTML 标签")
            return {"valid": False, "errors": errors}

        # 检查关键标签是否闭合
        for tag in ["html", "head", "body"]:
            open_tag = f"<{tag}"
            close_tag = f"</{tag}>"
            has_open = bool(re.search(open_tag, lower))
            has_close = close_tag in lower
            if has_open and not has_close:
                errors.append(f"{filename}: <{tag}> 标签未闭合")

        # 检查常见自闭合标签误用（简单检查）
        # 检查是否存在严重的不匹配引号
        double_quotes = content.count('"') - content.count('\\"')
        if double_quotes % 2 != 0:
            errors.append(f"{filename}: 引号不匹配（奇数个双引号）")

        return {"valid": len(errors) == 0, "errors": errors}

    def _get_output_dir(self, sample: Any) -> Path | None:
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
