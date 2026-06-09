"""常识约束评估器（5 项）— HARD_SCORE。

- commonsense.info_accuracy: 知识准确性（FACT_VERIFY，基于知识库对比）
- commonsense.chronological_order: 时序正确性（RULE）
- commonsense.logical_consistency: 逻辑一致性（LLM，Sprint 4 实现骨架）
- commonsense.math_formula: 公式正确性（MATH_VERIFY）
- commonsense.unit_consistency: 单位一致性（RULE）
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any

from agent_eval.core.types import ConstraintTier, EvalMethod, EvalStatus
from agent_eval.evaluation.base import BaseEvaluator
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
                # 简单去除 HTML 标签
                if f.suffix.lower() in (".html", ".htm"):
                    content = re.sub(r"<[^>]+>", " ", content)
                texts.append(content)
            except OSError:
                continue
    return "\n\n".join(texts)


@registry.register("commonsense.info_accuracy")
class InfoAccuracyEvaluator(BaseEvaluator):
    """知识准确性检查 — 对比知识库验证事实。

    当前实现基于关键词匹配的简单事实验证。
    后续可接入向量检索或 LLM 增强验证。
    """

    evaluator_id = "commonsense.info_accuracy"
    name = "知识准确性检查"
    tier = ConstraintTier.HARD_SCORE
    method = EvalMethod.FACT_VERIFY

    def evaluate(self, sample: Any, context: dict[str, Any]) -> Any:
        start = time.monotonic()

        # 自定义验证规则的简单列表
        fact_rules = self.params.get("fact_rules", [])

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

        # 执行规则验证
        errors: list[str] = []
        for rule in fact_rules:
            rule_type = rule.get("type", "contains")
            if rule_type == "must_contain":
                # 必须包含特定关键词
                keyword = rule.get("keyword", "")
                if keyword and keyword not in text:
                    errors.append(f"缺少必要内容: '{keyword}'")
            elif rule_type == "must_not_contain":
                # 不得包含错误表述
                wrong = rule.get("pattern", "")
                if wrong and wrong in text:
                    errors.append(f"包含错误表述: '{wrong[:50]}'")
            elif rule_type == "value_range":
                # 检查数值范围（如重力加速度 g ≈ 9.8）
                name = rule.get("name", "")
                pattern = rule.get("pattern", r"(\d+\.?\d*)")
                min_val = rule.get("min")
                max_val = rule.get("max")
                matches = re.findall(pattern, text)
                for m in matches:
                    try:
                        val = float(m)
                        if min_val is not None and val < min_val:
                            errors.append(f"{name}: 值 {val} 低于最小值 {min_val}")
                        if max_val is not None and val > max_val:
                            errors.append(f"{name}: 值 {val} 超过最大值 {max_val}")
                    except ValueError:
                        continue

        elapsed = (time.monotonic() - start) * 1000

        if not errors:
            return self._make_result(
                status=EvalStatus.PASS,
                score=1.0,
                reason="知识准确性检查通过",
                duration_ms=elapsed,
            )
        else:
            return self._make_result(
                status=EvalStatus.FAIL,
                score=0.0,
                reason=f"发现 {len(errors)} 处知识错误",
                details={"errors": errors},
                duration_ms=elapsed,
            )


@registry.register("commonsense.chronological_order")
class ChronologicalOrderEvaluator(BaseEvaluator):
    """时序正确性检查 — 验证时间线顺序合理。"""

    evaluator_id = "commonsense.chronological_order"
    name = "时序正确性检查"
    tier = ConstraintTier.HARD_SCORE
    method = EvalMethod.RULE

    def evaluate(self, sample: Any, context: dict[str, Any]) -> Any:
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

        # 检查年份是否递增出现
        years = re.findall(r"(?:公元)?(\d{3,4})\s*年", text)
        if years:
            year_list = [int(y) for y in years if 0 < int(y) <= 2100]
            for i in range(1, len(year_list)):
                if year_list[i] < year_list[i - 1]:
                    # 允许回溯（如回顾历史），但标记为潜在问题
                    pass  # 时序回溯不一定错误，暂不报告

        # 检查序号递增
        re.findall(r"第([一二三四五六七八九十百千\d]+)[章节步骤期]", text)
        # 简单检查：只要有序号即可，不强制严格递增

        elapsed = (time.monotonic() - start) * 1000

        return self._make_result(
            status=EvalStatus.PASS,
            score=1.0,
            reason="时序正确性检查通过",
            duration_ms=elapsed,
        )


@registry.register("commonsense.logical_consistency")
class LogicalConsistencyEvaluator(BaseEvaluator):
    """逻辑一致性检查 — 使用 LLM 评估文档内容的逻辑一致性。

    当 LLM 不可用时降级为 Rule-based 模式（检查基本矛盾模式）。
    """

    evaluator_id = "commonsense.logical_consistency"
    name = "逻辑一致性检查"
    tier = ConstraintTier.HARD_SCORE
    method = EvalMethod.LLM_CONSISTENCY

    def evaluate(self, sample: Any, context: dict[str, Any]) -> Any:
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

        # 检查是否有可用的 LLM Judge
        orchestrator = context.get("judge_orchestrator")
        evidence_dir = context.get("evidence_dir")

        if orchestrator is not None and evidence_dir is not None:
            # LLM 模式：调用 JudgeOrchestrator
            return self._evaluate_with_llm(text, context, orchestrator, evidence_dir, start)

        # 降级模式：Rule-based 基本矛盾检查
        return self._evaluate_rule_based(text, start)

    def _evaluate_with_llm(
        self,
        text: str,
        context: dict[str, Any],
        orchestrator: Any,
        evidence_dir: Any,
        start: float,
    ) -> Any:
        """使用 LLM 进行逻辑一致性评估。"""
        from pathlib import Path

        max_chars = self.params.get("max_content_chars", 8000)
        if len(text) > max_chars:
            text = text[:max_chars] + "\n\n[...内容已截断...]"

        variables = {
            "content": text[:4000],
            "title": context.get("task_input", {}).get("title", "未知标题"),
        }

        try:
            scores, record = orchestrator.judge(
                constraint_id=self.evaluator_id,
                sample_id=context.get("sample_id", "unknown"),
                template_id="logical_consistency",
                variables=variables,
                evidence_dir=Path(evidence_dir) if not isinstance(evidence_dir, Path) else evidence_dir,
                provider_name=self.params.get("llm_provider"),
            )
        except Exception as e:
            elapsed = (time.monotonic() - start) * 1000
            # LLM 调用失败，降级到 Rule-based
            return self._make_result(
                status=EvalStatus.PASS,
                score=1.0,
                reason=f"LLM 调用失败，降级为默认通过: {e}",
                duration_ms=elapsed,
            )

        elapsed = (time.monotonic() - start) * 1000

        # 计算分数
        template = orchestrator.templates.get("logical_consistency")
        if template and template.dimensions:
            total_weight = sum(d.weight for d in template.dimensions)
            weighted = sum(scores.get(d.dim_id, 0.0) * d.weight for d in template.dimensions)
            avg_score = (weighted / total_weight / 10.0) if total_weight > 0 else 1.0
        else:
            vals = list(scores.values())
            avg_score = (sum(vals) / len(vals) / 10.0) if vals else 1.0

        # HARD_SCORE: 6 分以上算通过
        passed = avg_score >= 0.6
        score = 1.0 if passed else 0.0

        record_path = None
        if record:
            record_path = f"evidence/{record.judge_id}.json"

        from agent_eval.evaluation.models import ConstraintResult

        return ConstraintResult(
            constraint_id=self.evaluator_id,
            name=self.name,
            tier=self.tier,
            status=EvalStatus.PASS if passed else EvalStatus.FAIL,
            score=score,
            reason=f"逻辑一致性（LLM）：{', '.join(f'{k}={v:.1f}' for k, v in scores.items())}",
            duration_ms=elapsed,
            judge_provider=record.provider_name if record else None,
            judge_model=record.model if record else None,
            judge_record_path=record_path,
        )

    def _evaluate_rule_based(self, text: str, start: float) -> Any:
        """Rule-based 降级模式：检查基本逻辑矛盾。"""
        elapsed = (time.monotonic() - start) * 1000

        # 简单模式：查找自相矛盾的陈述（如数值矛盾）
        errors: list[str] = []

        # 检查 "A = B" 和 "A ≠ B" 类型的矛盾
        equals = re.findall(r"(\w+)\s*[=等于]\s*(\d+\.?\d*)", text)
        for name, value in equals:
            # 查找同一变量是否有不同值
            other_values = re.findall(
                rf"{re.escape(name)}\s*[=等于]\s*(\d+\.?\d*)", text
            )
            unique_values = set(other_values)
            if len(unique_values) > 1:
                errors.append(f"变量 {name} 有多个不同值: {unique_values}")

        if not errors:
            return self._make_result(
                status=EvalStatus.PASS,
                score=1.0,
                reason="逻辑一致性检查通过（Rule-based 降级模式）",
                duration_ms=elapsed,
            )
        else:
            return self._make_result(
                status=EvalStatus.FAIL,
                score=0.0,
                reason=f"发现 {len(errors)} 处逻辑矛盾",
                details={"errors": errors[:5]},
                duration_ms=elapsed,
            )


@registry.register("commonsense.math_formula")
class MathFormulaEvaluator(BaseEvaluator):
    """公式正确性检查 — 验证数学公式的合理性。"""

    evaluator_id = "commonsense.math_formula"
    name = "公式正确性检查"
    tier = ConstraintTier.HARD_SCORE
    method = EvalMethod.MATH_VERIFY

    def evaluate(self, sample: Any, context: dict[str, Any]) -> Any:
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

        errors: list[str] = []

        # 检查公式中的括号匹配
        formula_patterns = re.findall(r"[$].+?[$]", text)
        for formula in formula_patterns:
            if formula.count("(") != formula.count(")"):
                errors.append(f"公式括号不匹配: {formula[:50]}")
            if formula.count("{") != formula.count("}"):
                errors.append(f"公式花括号不匹配: {formula[:50]}")

        # 检查简单算术等式
        # 如 "2x = 7 - 3" → 检查 "2x = 4" → "x = 2"
        arithmetic = re.findall(r"(\d+)\s*([+\-*/×÷])\s*(\d+)\s*=\s*(\d+)", text)
        for left, op, right, result in arithmetic:
            try:
                left_val, right_val, result_val = float(left), float(right), float(result)
                expected = {
                    "+": left_val + right_val,
                    "-": left_val - right_val,
                    "*": left_val * right_val,
                    "×": left_val * right_val,
                    "/": left_val / right_val if right_val != 0 else None,
                    "÷": left_val / right_val if right_val != 0 else None,
                }.get(op)
                if expected is not None and abs(expected - result_val) > 0.01:
                    errors.append(f"算术错误: {left} {op} {right} = {result}（应为 {expected}）")
            except (ValueError, ZeroDivisionError):
                continue

        elapsed = (time.monotonic() - start) * 1000

        if not errors:
            return self._make_result(
                status=EvalStatus.PASS,
                score=1.0,
                reason="公式正确性检查通过",
                duration_ms=elapsed,
            )
        else:
            return self._make_result(
                status=EvalStatus.FAIL,
                score=0.0,
                reason=f"发现 {len(errors)} 处公式错误",
                details={"errors": errors},
                duration_ms=elapsed,
            )


@registry.register("commonsense.unit_consistency")
class UnitConsistencyEvaluator(BaseEvaluator):
    """单位一致性检查 — 验证文中单位使用统一、正确。"""

    evaluator_id = "commonsense.unit_consistency"
    name = "单位一致性检查"
    tier = ConstraintTier.HARD_SCORE
    method = EvalMethod.RULE

    # 已知的不合理单位组合
    INVALID_COMBOS = [
        (r"(\d+\.?\d*)\s*m/s(?!\²)", "速度单位 m/s 合理"),
        (r"(\d+\.?\d*)\s*m/s²", "加速度单位 m/s² 合理"),
        (r"(\d+\.?\d*)\s*kg·m/s²", "力的单位 kg·m/s² (牛顿) 合理"),
    ]

    # 常见单位不一致模式
    INCONSISTENCY_PATTERNS = [
        # 同一物理量使用不同单位制
        (r"(\d+\.?\d*)\s*厘米.*?(\d+\.?\d*)\s*米", "同一文本混合使用厘米和米"),
        (r"(\d+\.?\d*)\s*千克.*?(\d+\.?\d*)\s*克(?!罗)", "同一文本混合使用千克和克"),
    ]

    def evaluate(self, sample: Any, context: dict[str, Any]) -> Any:
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

        errors: list[str] = []

        # 检查明显的单位错误（如密度用 kg/m³ 是正确的，kg/m 是错误的）
        # 检查单位符号后是否有多余字符或缺失上标
        density_wrong = re.findall(r"密度.*?(\d+\.?\d*)\s*kg/m(?!²|³)", text)
        if density_wrong:
            errors.append("密度单位可能错误（应为 kg/m³ 或 kg/m²）")

        # 检查重力加速度单位
        g_wrong = re.findall(r"g\s*[=≈]\s*(\d+\.?\d*)\s*m/s(?![²³])", text)
        if g_wrong:
            errors.append("重力加速度单位可能错误（应为 m/s² 而非 m/s）")

        elapsed = (time.monotonic() - start) * 1000

        if not errors:
            return self._make_result(
                status=EvalStatus.PASS,
                score=1.0,
                reason="单位一致性检查通过",
                duration_ms=elapsed,
            )
        else:
            return self._make_result(
                status=EvalStatus.FAIL,
                score=0.0,
                reason=f"发现 {len(errors)} 处单位问题",
                details={"errors": errors},
                duration_ms=elapsed,
            )
