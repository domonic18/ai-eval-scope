"""格式约束评估器（5 项）— HARD_GATE。

- format.response_format: 文件格式检查（MD/HTML）
- format.document_count: 文档数量检查
- format.structure_compliance: 结构规范性（标题层级）
- format.html_validity: HTML 标签有效性
- format.directory_structure: 目录结构检查（仅目录模式）
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

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

        from agent_eval.evaluation.models import ConstraintResult

        start = time.monotonic()
        allowed = set(self.params.get("allowed_formats", ["md", "html"]))
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
        files = [
            f
            for f in output_dir.rglob("*")
            if f.is_file() and f.name != "_manifest.json"
        ]

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
                duration_ms=elapsed,
            )
        else:
            return self._make_result(
                status=EvalStatus.FAIL,
                score=0.0,
                reason=f"格式不合规: {'; '.join(invalid_files[:5])}",
                details={"invalid_files": invalid_files},
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


@registry.register("format.document_count")
class DocumentCountEvaluator(BaseEvaluator):
    """文档数量检查 — 验证输出文档数量在约束范围内。"""

    evaluator_id = "format.document_count"
    name = "文档数量检查"
    tier = ConstraintTier.HARD_GATE
    method = EvalMethod.RULE

    def evaluate(self, sample: Any, context: dict[str, Any]) -> Any:
        import time

        from agent_eval.evaluation.models import ConstraintResult

        start = time.monotonic()

        constraints = context.get("constraints", {})
        min_docs = self.params.get("min_documents", constraints.get("min_documents", 1))
        max_docs = self.params.get("max_documents", constraints.get("max_documents", 20))
        # 也支持 min/max 简写
        min_docs = self.params.get("min", min_docs)
        max_docs = self.params.get("max", max_docs)

        output_dir = self._get_output_dir(sample)
        if output_dir is None or not output_dir.exists():
            elapsed = (time.monotonic() - start) * 1000
            return self._make_result(
                status=EvalStatus.FAIL,
                score=0.0,
                reason="输出目录不存在",
                duration_ms=elapsed,
            )

        # 统计文件数（排除 _manifest.json）
        files = [
            f
            for f in output_dir.rglob("*")
            if f.is_file() and f.name != "_manifest.json"
        ]
        actual = len(files)
        elapsed = (time.monotonic() - start) * 1000

        passed = min_docs <= actual <= max_docs
        return self._make_result(
            status=EvalStatus.PASS if passed else EvalStatus.FAIL,
            score=1.0 if passed else 0.0,
            reason=f"实际 {actual} 个文档，要求 [{min_docs}, {max_docs}]",
            details={"actual": actual, "min": min_docs, "max": max_docs},
            duration_ms=elapsed,
        )

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


@registry.register("format.structure_compliance")
class StructureComplianceEvaluator(BaseEvaluator):
    """结构规范性检查 — 验证标题层级合理、章节结构完整。"""

    evaluator_id = "format.structure_compliance"
    name = "结构规范性检查"
    tier = ConstraintTier.HARD_GATE
    method = EvalMethod.RULE

    def evaluate(self, sample: Any, context: dict[str, Any]) -> Any:
        import time

        from agent_eval.evaluation.models import ConstraintResult

        start = time.monotonic()

        max_heading_depth = self.params.get("max_heading_depth", 6)
        require_toc = self.params.get("require_toc", False)

        output_dir = self._get_output_dir(sample)
        if output_dir is None or not output_dir.exists():
            elapsed = (time.monotonic() - start) * 1000
            return self._make_result(
                status=EvalStatus.FAIL,
                score=0.0,
                reason="输出目录不存在",
                duration_ms=elapsed,
            )

        files = self._collect_content_files(output_dir)
        if not files:
            elapsed = (time.monotonic() - start) * 1000
            return self._make_result(
                status=EvalStatus.FAIL,
                score=0.0,
                reason="无可检查的文档文件",
                duration_ms=elapsed,
            )

        issues: list[str] = []
        has_heading = False

        for f in files:
            try:
                content = f.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue

            ext = f.suffix.lower()
            if ext in (".md", ".markdown"):
                headings = self._extract_md_headings(content)
            elif ext in (".html", ".htm"):
                headings = self._extract_html_headings(content)
            else:
                continue

            if headings:
                has_heading = True
                # 检查标题层级是否超出限制
                for level, text in headings:
                    if level > max_heading_depth:
                        issues.append(f"{f.name}: 标题层级 {level} 超出限制 {max_heading_depth} — '{text[:30]}'")

        elapsed = (time.monotonic() - start) * 1000

        if not has_heading:
            return self._make_result(
                status=EvalStatus.FAIL,
                score=0.0,
                reason="文档中未发现任何标题结构",
                duration_ms=elapsed,
            )

        if issues:
            return self._make_result(
                status=EvalStatus.FAIL,
                score=0.0,
                reason=f"结构不合规: {'; '.join(issues[:5])}",
                details={"issues": issues},
                duration_ms=elapsed,
            )

        return self._make_result(
            status=EvalStatus.PASS,
            score=1.0,
            reason="文档结构规范，标题层级合理",
            duration_ms=elapsed,
        )

    def _collect_content_files(self, output_dir: Path) -> list[Path]:
        """收集 Markdown 和 HTML 文件。"""
        files = []
        for ext in ("*.md", "*.markdown", "*.html", "*.htm"):
            files.extend(output_dir.rglob(ext))
        return sorted(files)

    def _extract_md_headings(self, content: str) -> list[tuple[int, str]]:
        """提取 Markdown 标题 (# level text)。"""
        headings = []
        for line in content.split("\n"):
            match = re.match(r"^(#{1,6})\s+(.+)$", line)
            if match:
                headings.append((len(match.group(1)), match.group(2).strip()))
        return headings

    def _extract_html_headings(self, content: str) -> list[tuple[int, str]]:
        """提取 HTML 标题 (h1-h6)。"""
        headings = []
        for match in re.finditer(r"<h([1-6])[^>]*>(.*?)</h\1>", content, re.DOTALL | re.IGNORECASE):
            level = int(match.group(1))
            text = re.sub(r"<[^>]+>", "", match.group(2)).strip()
            if text:
                headings.append((level, text))
        return headings

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


@registry.register("format.html_validity")
class HtmlValidityEvaluator(BaseEvaluator):
    """HTML 有效性检查 — 验证 HTML 标签闭合、可正常解析。"""

    evaluator_id = "format.html_validity"
    name = "HTML 有效性检查"
    tier = ConstraintTier.HARD_GATE
    method = EvalMethod.RULE

    def evaluate(self, sample: Any, context: dict[str, Any]) -> Any:
        import time

        from agent_eval.evaluation.models import ConstraintResult

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
                duration_ms=elapsed,
            )
        else:
            return self._make_result(
                status=EvalStatus.FAIL,
                score=0.0,
                reason=f"HTML 校验失败: {'; '.join(issues[:5])}",
                details={"issues": issues, "valid_count": valid_count, "total": len(html_files)},
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


@registry.register("format.directory_structure")
class DirectoryStructureEvaluator(BaseEvaluator):
    """目录结构检查 — 仅目录模式激活。

    验证模块数量、层级深度、模块名称与预期匹配。
    扁平文件模式下自动跳过（score = 1.0）。
    """

    evaluator_id = "format.directory_structure"
    name = "目录结构检查"
    tier = ConstraintTier.HARD_GATE
    method = EvalMethod.RULE

    def evaluate(self, sample: Any, context: dict[str, Any]) -> Any:
        import time

        from agent_eval.evaluation.models import ConstraintResult

        start = time.monotonic()

        manifest = context.get("directory_manifest")
        if manifest is None:
            # 尝试从 sample 的 output_dir 读取 _manifest.json
            manifest = self._try_load_manifest(sample)

        if manifest is None:
            elapsed = (time.monotonic() - start) * 1000
            return self._make_result(
                status=EvalStatus.PASS,
                score=1.0,
                reason="非目录模式，跳过",
                duration_ms=elapsed,
            )

        # manifest 可以是 dict 或 Pydantic model
        manifest_dict = self._to_dict(manifest)

        constraints = context.get("constraints", {})
        # 合并 params 中的约束
        for key in ("expected_modules", "hierarchy_depth", "expected_module_names"):
            if key in self.params and self.params[key] is not None:
                constraints.setdefault(key, self.params[key])

        checks: list[tuple[str, bool, str]] = []

        # 1. 模块数量检查
        expected_modules = constraints.get("expected_modules")
        if expected_modules is not None:
            actual_modules = len(manifest_dict.get("modules", []))
            checks.append((
                "模块数量",
                actual_modules == expected_modules,
                f"实际{actual_modules}个模块，期望{expected_modules}个",
            ))

        # 2. 层级深度检查
        expected_depth = constraints.get("hierarchy_depth")
        if expected_depth is not None:
            actual_depth = manifest_dict.get("hierarchy_depth", 0)
            checks.append((
                "目录深度",
                actual_depth <= expected_depth,
                f"实际{actual_depth}层，要求≤{expected_depth}层",
            ))

        # 3. 模块名称匹配
        expected_names = constraints.get("expected_module_names", [])
        if expected_names:
            actual_names = [m.get("name", "") for m in manifest_dict.get("modules", [])]
            missing = set(expected_names) - set(actual_names)
            checks.append((
                "模块名称",
                len(missing) == 0,
                f"缺失模块: {missing}" if missing else "模块名称匹配",
            ))

        elapsed = (time.monotonic() - start) * 1000

        if not checks:
            return self._make_result(
                status=EvalStatus.PASS,
                score=1.0,
                reason="目录模式已激活，无具体约束需要检查",
                duration_ms=elapsed,
            )

        all_passed = all(passed for _, passed, _ in checks)
        reason = "; ".join(
            f"{n}({'✓' if p else '✗'}: {r})" for n, p, r in checks
        )

        return self._make_result(
            status=EvalStatus.PASS if all_passed else EvalStatus.FAIL,
            score=1.0 if all_passed else 0.0,
            reason=reason,
            details={"checks": [{"name": n, "passed": p, "reason": r} for n, p, r in checks]},
            duration_ms=elapsed,
            module_results=[
                {"module": m.get("name", ""), "file_count": m.get("file_count", 0), "passed": True}
                for m in manifest_dict.get("modules", [])
            ] if all_passed else None,
        )

    def _try_load_manifest(self, sample: Any) -> dict | None:
        """尝试从 sample 的 output 目录加载 _manifest.json。"""
        import json

        output_dir = None
        if isinstance(sample, Path):
            output_dir = sample / "output" if sample.is_dir() else sample.parent / "output"
        elif hasattr(sample, "output_dir") and sample.output_dir is not None:
            output_dir = Path(sample.output_dir)
        elif isinstance(sample, dict):
            p = sample.get("package_dir") or sample.get("output_dir")
            if p:
                p = Path(p)
                output_dir = p / "output" if p.is_dir() and (p / "output").exists() else p

        if output_dir is None:
            return None

        manifest_path = output_dir / "_manifest.json"
        if manifest_path.exists():
            try:
                return json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return None
        return None

    def _to_dict(self, manifest: Any) -> dict:
        """将 manifest 转为 dict。"""
        if isinstance(manifest, dict):
            return manifest
        if hasattr(manifest, "model_dump"):
            return manifest.model_dump()
        if hasattr(manifest, "__dict__"):
            return manifest.__dict__
        return {}
