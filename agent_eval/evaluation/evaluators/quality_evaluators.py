"""软约束与偏好约束评估器（7 项）。

Rule-based:
- soft.content_density: 内容密度（字符数/段落/图片比）
- soft.visual_consistency: 视觉一致性（HTML 样式一致性检查）

LLM Judge:
- soft.teaching_logic: 教学逻辑（LLM_JUDGE）
- soft.content_diversity: 内容多样性（LLM_JUDGE）
- pref.style_preference: 风格偏好（LLM_JUDGE）
- pref.depth_preference: 深度偏好（LLM_JUDGE）
- pref.request_fulfillment: 需求满足度（LLM_JUDGE）
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from agent_eval.core.types import ConstraintTier, EvalMethod, EvalStatus
from agent_eval.evaluation.base import BaseEvaluator
from agent_eval.evaluation.models import ConstraintResult
from agent_eval.evaluation.registry import registry


def _get_output_dir(sample: Any) -> Path | None:
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


def _collect_text_content(output_dir: Path) -> str:
    """收集目录下所有文档的文本内容。"""
    texts: list[str] = []
    for ext in ("*.md", "*.markdown", "*.html", "*.htm"):
        for f in output_dir.rglob(ext):
            try:
                content = f.read_text(encoding="utf-8", errors="ignore")
                if f.suffix.lower() in (".html", ".htm"):
                    content = re.sub(r"<[^>]+>", " ", content)
                texts.append(content)
            except OSError:
                continue
    return "\n\n".join(texts)


def _collect_file_names(output_dir: Path) -> list[str]:
    """收集目录下所有文档文件名。"""
    names: list[str] = []
    for ext in ("*.md", "*.markdown", "*.html", "*.htm"):
        for f in output_dir.rglob(ext):
            names.append(f.name)
    return sorted(names)


# ─── Rule-based 软约束评估器 ───


@registry.register("soft.content_density")
class ContentDensityEvaluator(BaseEvaluator):
    """内容密度检查 — 评估文本内容的充实度。

    基于字符数、段落数、列表项数和标题数等指标综合计算密度分数。
    """

    evaluator_id = "soft.content_density"
    name = "内容密度"
    tier = ConstraintTier.SOFT
    method = EvalMethod.RULE

    # 密度评估阈值
    MIN_CHARS_PER_PARAGRAPH = 50  # 每段最少字符数（过低说明内容空洞）
    MAX_CHARS_PER_PARAGRAPH = 2000  # 每段最多字符数（过高说明排版差）
    OPTIMAL_PARAGRAPH_COUNT = 5  # 理想段落数
    MIN_HEADING_RATIO = 0.1  # 标题/段落最低比率

    def evaluate(self, sample: Any, context: dict[str, Any]) -> ConstraintResult:
        import time

        start = time.monotonic()

        output_dir = _get_output_dir(sample)
        if output_dir is None or not output_dir.exists():
            elapsed = (time.monotonic() - start) * 1000
            return self._make_result(
                status=EvalStatus.FAIL,
                score=0.0,
                reason="输出目录不存在",
                duration_ms=elapsed,
            )

        text = _collect_text_content(output_dir)
        if not text.strip():
            elapsed = (time.monotonic() - start) * 1000
            return self._make_result(
                status=EvalStatus.FAIL,
                score=0.0,
                reason="文档内容为空",
                duration_ms=elapsed,
            )

        # 计算指标
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        headings = re.findall(r"^#{1,6}\s+.+$", text, re.MULTILINE)
        list_items = re.findall(r"^\s*[-*+]\s+.+$", text, re.MULTILINE)
        total_chars = len(text.strip())

        score = 0.0
        details: dict[str, Any] = {
            "total_chars": total_chars,
            "paragraphs": len(paragraphs),
            "headings": len(headings),
            "list_items": len(list_items),
        }
        reasons: list[str] = []

        # 1. 段落数量评分（0-0.3）
        if len(paragraphs) == 0:
            para_score = 0.0
            reasons.append("无有效段落")
        elif len(paragraphs) < 2:
            para_score = 0.1
            reasons.append(f"段落数过少（{len(paragraphs)}段）")
        elif len(paragraphs) <= self.OPTIMAL_PARAGRAPH_COUNT * 3:
            para_score = 0.3
        else:
            para_score = 0.2
            reasons.append(f"段落数偏多（{len(paragraphs)}段）")

        # 2. 平均段落长度评分（0-0.3）
        if paragraphs:
            avg_len = total_chars / len(paragraphs)
            if self.MIN_CHARS_PER_PARAGRAPH <= avg_len <= self.MAX_CHARS_PER_PARAGRAPH:
                length_score = 0.3
            elif avg_len < self.MIN_CHARS_PER_PARAGRAPH:
                length_score = 0.1
                reasons.append(f"段落平均长度过短（{avg_len:.0f}字符）")
            else:
                length_score = 0.15
                reasons.append(f"段落平均长度过长（{avg_len:.0f}字符）")
        else:
            length_score = 0.0

        # 3. 结构丰富度评分（0-0.2）
        structure_score = 0.0
        if headings:
            structure_score += 0.1
        if list_items:
            structure_score += 0.1
        elif not headings:
            reasons.append("缺少标题和列表结构")

        # 4. 内容充实度评分（0-0.2）
        if total_chars > 1000:
            content_score = 0.2
        elif total_chars > 500:
            content_score = 0.15
        elif total_chars > 100:
            content_score = 0.1
            reasons.append("内容偏少")
        else:
            content_score = 0.05
            reasons.append("内容严重不足")

        score = para_score + length_score + structure_score + content_score
        score = min(1.0, max(0.0, score))

        elapsed = (time.monotonic() - start) * 1000
        details["score_breakdown"] = {
            "paragraphs": para_score,
            "length": length_score,
            "structure": structure_score,
            "content_volume": content_score,
        }
        details["files_checked"] = _collect_file_names(output_dir)

        reason = "内容密度" + ("良好" if score >= 0.6 else "不足")
        if reasons:
            reason += "：" + "；".join(reasons)

        return self._make_result(
            status=EvalStatus.PASS if score >= 0.4 else EvalStatus.FAIL,
            score=score,
            reason=reason,
            details=details,
            duration_ms=elapsed,
        )


@registry.register("soft.visual_consistency")
class VisualConsistencyEvaluator(BaseEvaluator):
    """视觉一致性检查 — 评估 HTML 文档的样式一致性。

    检查字体、颜色、间距等视觉元素的统一程度。
    """

    evaluator_id = "soft.visual_consistency"
    name = "视觉一致性"
    tier = ConstraintTier.SOFT
    method = EvalMethod.RULE

    def evaluate(self, sample: Any, context: dict[str, Any]) -> ConstraintResult:
        import time

        start = time.monotonic()

        output_dir = _get_output_dir(sample)
        if output_dir is None or not output_dir.exists():
            elapsed = (time.monotonic() - start) * 1000
            return self._make_result(
                status=EvalStatus.FAIL,
                score=0.0,
                reason="输出目录不存在",
                duration_ms=elapsed,
            )

        # 检查是否存在 HTML 文件
        html_files = list(output_dir.rglob("*.html")) + list(output_dir.rglob("*.htm"))
        if not html_files:
            # 纯 Markdown 文档，给予中等分数
            elapsed = (time.monotonic() - start) * 1000
            return self._make_result(
                status=EvalStatus.PASS,
                score=0.7,
                reason="无 HTML 文件，Markdown 模式下视觉一致性默认 0.7",
                duration_ms=elapsed,
            )

        issues: list[str] = []
        details: dict[str, Any] = {"html_files": len(html_files)}

        # 收集所有样式信息
        font_families: set[str] = set()
        colors: set[str] = set()
        font_sizes: set[str] = set()

        for html_file in html_files:
            try:
                content = html_file.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue

            # 提取内联样式
            inline_styles = re.findall(r'style\s*=\s*"([^"]*)"', content)
            for style in inline_styles:
                # 提取 font-family
                ff = re.findall(r"font-family\s*:\s*([^;]+)", style, re.IGNORECASE)
                font_families.update(f.strip().lower() for f in ff)

                # 提取 color
                cl = re.findall(r"(?:color|background-color)\s*:\s*([^;]+)", style, re.IGNORECASE)
                colors.update(c.strip().lower() for c in cl)

                # 提取 font-size
                fs = re.findall(r"font-size\s*:\s*([^;]+)", style, re.IGNORECASE)
                font_sizes.update(s.strip().lower() for s in fs)

            # 提取 <style> 块中的样式
            style_blocks = re.findall(r"<style[^>]*>(.*?)</style>", content, re.DOTALL | re.IGNORECASE)
            for block in style_blocks:
                ff = re.findall(r"font-family\s*:\s*([^;]+)", block, re.IGNORECASE)
                font_families.update(f.strip().lower() for f in ff)
                cl = re.findall(r"color\s*:\s*([^;]+)", block, re.IGNORECASE)
                colors.update(c.strip().lower() for c in cl)

        # 计算一致性分数
        score = 1.0
        details["font_families"] = len(font_families)
        details["colors"] = len(colors)
        details["font_sizes"] = len(font_sizes)

        # 字体族过多扣分
        if len(font_families) > 4:
            score -= 0.2
            issues.append(f"使用 {len(font_families)} 种字体（建议 ≤ 4）")

        # 颜色过多扣分
        if len(colors) > 10:
            score -= 0.2
            issues.append(f"使用 {len(colors)} 种颜色（建议 ≤ 10）")

        # 字号过多扣分
        if len(font_sizes) > 6:
            score -= 0.2
            issues.append(f"使用 {len(font_sizes)} 种字号（建议 ≤ 6）")

        score = max(0.0, min(1.0, score))

        elapsed = (time.monotonic() - start) * 1000
        details["files_checked"] = [f.name for f in html_files]
        details["font_list"] = sorted(font_families)
        details["color_list"] = sorted(colors)

        reason = "视觉一致性" + ("良好" if score >= 0.6 else "欠佳")
        if issues:
            reason += "：" + "；".join(issues)

        return self._make_result(
            status=EvalStatus.PASS if score >= 0.4 else EvalStatus.FAIL,
            score=score,
            reason=reason,
            details=details,
            duration_ms=elapsed,
        )


# ─── LLM Judge 评估器 ───


class BaseLLMJudgeEvaluator(BaseEvaluator):
    """LLM Judge 评估器基类 — 处理 LLM 评估的通用流程。

    子类只需设置类属性 template_id 并可选择性覆盖 _build_variables()。
    LLM 调用依赖 context 中的 judge_orchestrator 和 evidence_dir。
    当 orchestrator 不可用时，降级为 Rule-based 默认通过模式。
    """

    template_id: str = ""  # 子类必须设置

    def evaluate(self, sample: Any, context: dict[str, Any]) -> ConstraintResult:
        import time

        start = time.monotonic()

        # 检查是否有可用的 JudgeOrchestrator
        orchestrator = context.get("judge_orchestrator")
        evidence_dir = context.get("evidence_dir")

        if orchestrator is None or evidence_dir is None:
            # 降级模式：LLM 不可用时默认通过
            elapsed = (time.monotonic() - start) * 1000
            return ConstraintResult(
                constraint_id=self.evaluator_id,
                name=self.name,
                tier=self.tier,
                status=EvalStatus.PASS,
                score=0.7,
                reason=f"{self.name}（LLM 不可用，降级模式默认 0.7）",
                duration_ms=elapsed,
            )

        # 收集文档内容
        output_dir = _get_output_dir(sample)
        text = ""
        if output_dir and output_dir.exists():
            text = _collect_text_content(output_dir)

        if not text.strip():
            elapsed = (time.monotonic() - start) * 1000
            return self._make_result(
                status=EvalStatus.FAIL,
                score=0.0,
                reason="文档内容为空，无法进行 LLM 评估",
                duration_ms=elapsed,
            )

        # 截断过长内容（避免超过 token 限制）
        max_chars = self.params.get("max_content_chars", 8000)
        if len(text) > max_chars:
            text = text[:max_chars] + "\n\n[...内容已截断...]"

        # 构建模板变量
        variables = self._build_variables(text, context)

        # 调用 JudgeOrchestrator
        try:
            scores, record = orchestrator.judge(
                constraint_id=self.evaluator_id,
                sample_id=context.get("sample_id", "unknown"),
                template_id=self.template_id,
                variables=variables,
                evidence_dir=Path(evidence_dir) if not isinstance(evidence_dir, Path) else evidence_dir,
                provider_name=self.params.get("llm_provider"),
            )
        except Exception as e:
            elapsed = (time.monotonic() - start) * 1000
            return self._make_result(
                status=EvalStatus.ERROR,
                score=0.0,
                reason=f"LLM Judge 调用失败: {e}",
                duration_ms=elapsed,
            )

        elapsed = (time.monotonic() - start) * 1000

        # 计算加权分数：各维度得分 × 权重 / 总权重
        template = orchestrator.templates.get(self.template_id)
        if template and template.dimensions:
            total_weight = sum(d.weight for d in template.dimensions)
            weighted_score = sum(
                scores.get(d.dim_id, 0.0) * d.weight for d in template.dimensions
            )
            normalized = (weighted_score / total_weight / 10.0) if total_weight > 0 else 0.0
        else:
            # 无维度信息，取平均
            vals = list(scores.values())
            normalized = (sum(vals) / len(vals) / 10.0) if vals else 0.0

        normalized = max(0.0, min(1.0, normalized))

        # 构建评估原因
        score_parts = [f"{k}: {v:.1f}" for k, v in scores.items()]
        reason = f"{self.name}（LLM 评估）：{', '.join(score_parts)}"

        # 获取 judge record 路径
        record_path = None
        if record:
            judge_id = record.judge_id
            record_path = f"evidence/{judge_id}.json"

        return ConstraintResult(
            constraint_id=self.evaluator_id,
            name=self.name,
            tier=self.tier,
            status=EvalStatus.PASS if normalized >= 0.4 else EvalStatus.FAIL,
            score=normalized,
            reason=reason,
            details={"scores": scores, "confidence": record.confidence if record else {}},
            duration_ms=elapsed,
            judge_provider=record.provider_name if record else None,
            judge_model=record.model if record else None,
            judge_record_path=record_path,
        )

    def _build_variables(self, text: str, context: dict[str, Any]) -> dict[str, Any]:
        """构建 Prompt 模板变量。子类可覆盖以添加特定变量。"""
        return {
            "content": text[:4000],
            "title": context.get("task_input", {}).get("title", "未知标题"),
            "subject": context.get("task_input", {}).get("subject", "未知学科"),
        }


@registry.register("soft.teaching_logic")
class TeachingLogicEvaluator(BaseLLMJudgeEvaluator):
    """教学逻辑评估 — LLM 评审课件的教学结构、知识递进和互动设计。"""

    evaluator_id = "soft.teaching_logic"
    name = "教学逻辑"
    tier = ConstraintTier.SOFT
    method = EvalMethod.LLM_JUDGE
    template_id = "pedagogical_logic"


@registry.register("soft.content_diversity")
class ContentDiversityEvaluator(BaseLLMJudgeEvaluator):
    """内容多样性评估 — LLM 评审内容的丰富度和多样性。"""

    evaluator_id = "soft.content_diversity"
    name = "内容多样性"
    tier = ConstraintTier.SOFT
    method = EvalMethod.LLM_JUDGE
    template_id = "content_diversity"

    def _build_variables(self, text: str, context: dict[str, Any]) -> dict[str, Any]:
        variables = super()._build_variables(text, context)
        # 统计内容类型多样性
        has_formula = bool(re.findall(r"[$].+?[$]", text))
        has_table = bool(re.search(r"<table|^\|.*\|$", text, re.MULTILINE))
        has_image = bool(re.search(r"!\[|<img ", text))
        has_list = bool(re.search(r"^\s*[-*+]\s+", text, re.MULTILINE))
        variables["has_formula"] = "是" if has_formula else "否"
        variables["has_table"] = "是" if has_table else "否"
        variables["has_image"] = "是" if has_image else "否"
        variables["has_list"] = "是" if has_list else "否"
        return variables


@registry.register("pref.style_preference")
class StylePreferenceEvaluator(BaseLLMJudgeEvaluator):
    """风格偏好评估 — LLM 评审文档风格是否符合要求。"""

    evaluator_id = "pref.style_preference"
    name = "风格偏好"
    tier = ConstraintTier.PREFERENCE
    method = EvalMethod.LLM_JUDGE
    template_id = "style_preference"


@registry.register("pref.depth_preference")
class DepthPreferenceEvaluator(BaseLLMJudgeEvaluator):
    """深度偏好评估 — LLM 评审内容深度是否满足要求。"""

    evaluator_id = "pref.depth_preference"
    name = "深度偏好"
    tier = ConstraintTier.PREFERENCE
    method = EvalMethod.LLM_JUDGE
    template_id = "depth_preference"


@registry.register("pref.request_fulfillment")
class RequestFulfillmentEvaluator(BaseLLMJudgeEvaluator):
    """需求满足度评估 — LLM 评审产出是否满足原始需求。"""

    evaluator_id = "pref.request_fulfillment"
    name = "需求满足度"
    tier = ConstraintTier.PREFERENCE
    method = EvalMethod.LLM_JUDGE
    template_id = "request_fulfillment"

    def _build_variables(self, text: str, context: dict[str, Any]) -> dict[str, Any]:
        variables = super()._build_variables(text, context)
        # 添加原始需求信息
        task_input = context.get("task_input", {})
        variables["original_request"] = task_input.get("input", "未提供原始需求")
        variables["expected_output"] = task_input.get("expected", "未提供预期输出描述")
        return variables
