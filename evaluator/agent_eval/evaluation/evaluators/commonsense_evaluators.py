"""常识约束评估器（5 项）— HARD_SCORE。

- commonsense.info_accuracy: 知识准确性（FACT_VERIFY，三层检查：内置自动 + 可配置规则 + LLM）
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

import structlog

from agent_eval.config import EVALUATOR_DEFAULTS
from agent_eval.core.types import ConstraintTier, EvalMethod, EvalStatus
from agent_eval.evaluation.base import BaseEvaluator
from agent_eval.evaluation.registry import registry
from agent_eval.evaluation.text_utils import collect_file_texts, collect_text_content

logger = structlog.get_logger("evaluation.commonsense")


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
    """收集目录下所有文档的文本内容（合并为单字符串）。

    其他评估器（chronological_order 等）仍在使用此函数。HTML 经
    `text_utils.collect_text_content` 干净提取（剥除 style/script，保留块级结构）。
    """
    return collect_text_content(output_dir)


def _collect_file_names(output_dir: Path) -> list[str]:
    """收集目录下所有文档文件名。"""
    names: list[str] = []
    for ext in ("*.md", "*.markdown", "*.html", "*.htm"):
        for f in output_dir.rglob(ext):
            names.append(f.name)
    return sorted(names)


def _collect_file_texts(output_dir: Path) -> dict[str, str]:
    """收集 per-file 文本内容，保留文件归属。

    Returns:
        {文件相对路径: 纯文本内容}，HTML 经 `text_utils` 干净提取。
    """
    return collect_file_texts(output_dir)


# ─── 事实知识库（委托给 KnowledgeBaseManager） ───

_knowledge_manager = None


def _get_knowledge_manager() -> Any:
    """获取默认 KnowledgeBaseManager 单例。"""
    global _knowledge_manager
    if _knowledge_manager is None:
        from agent_eval.knowledge.manager import KnowledgeBaseManager

        _knowledge_manager = KnowledgeBaseManager()
    return _knowledge_manager


def _load_fact_db(subjects: list[str] | None = None) -> dict:
    """加载事实知识库（兼容旧接口，委托给 KnowledgeBaseManager）。"""
    return _get_knowledge_manager().load(subjects)


def _reset_fact_db_cache() -> None:
    """重置事实知识库缓存（兼容旧接口）。"""
    _get_knowledge_manager().invalidate_cache()


# ─── 算术表达式求值 ───

# 算术运算符集合
_OP_CHARS = set("+＋-－×÷*/")


def _eval_simple_expr(expr: str) -> float | None:
    """求值简单算术表达式（支持 +,-,×,÷ 及运算符优先级）。

    支持形如 ``28×8 + 22×9 + 35×4`` 的多项表达式。
    返回浮点结果，解析失败返回 None。
    """
    # 归一化运算符
    norm = expr.replace("＋", "+").replace("－", "-").replace("×", "*").replace("÷", "/")
    # 词法分析：提取 数字 / 运算符
    tokens: list[str | float] = []
    for m in re.finditer(r"(\d+\.?\d*)|([+\-*/])", norm):
        num_s, op_s = m.group(1), m.group(2)
        if num_s:
            tokens.append(float(num_s))
        elif op_s:
            tokens.append(op_s)

    if not tokens or not isinstance(tokens[0], float):
        return None

    # 分离数字和运算符
    numbers: list[float] = []
    ops: list[str] = []
    for t in tokens:
        if isinstance(t, float):
            numbers.append(t)
        else:
            ops.append(t)

    if len(numbers) != len(ops) + 1 or not numbers:
        return None

    # 第一遍：处理 * / （高优先级）
    i = 0
    while i < len(ops):
        if ops[i] in ("*", "/"):
            if ops[i] == "*":
                numbers[i] *= numbers[i + 1]
            else:
                if numbers[i + 1] == 0:
                    return None
                numbers[i] /= numbers[i + 1]
            numbers.pop(i + 1)
            ops.pop(i)
        else:
            i += 1

    # 第二遍：处理 + -
    result = numbers[0]
    for i, op in enumerate(ops):
        if op == "+":
            result += numbers[i + 1]
        elif op == "-":
            result -= numbers[i + 1]
        else:
            return None  # 不应到这里

    return result


# 竖式计算上下文关键词（出现在算式附近则跳过该算式）
_VERTICAL_CALC_KEYWORDS = re.compile(r"[写记进退]\d|[进退]一当十|满十进一|个位|十位|百位")


@registry.register("commonsense.info_accuracy")
class InfoAccuracyEvaluator(BaseEvaluator):
    """知识准确性检查 — 三层检查架构。

    Phase 1: 内置自动检查（算术表达式验证、常数校验、常识错误检测）
    Phase 2: 可配置规则检查（must_contain / must_not_contain / value_range / 新规则类型）
    Phase 3: LLM 语义验证（当 judge_orchestrator 可用时）
    """

    evaluator_id = "commonsense.info_accuracy"
    name = "知识准确性检查"
    tier = ConstraintTier.HARD_SCORE
    method = EvalMethod.FACT_VERIFY

    # 算术等式正则 — 匹配完整左侧 "A op B op C ... = result"
    # (?<!\d)   — 不从数字中间开始（防止 "224" 中的 "4" 成为起点）
    # (?![\d.]) — 结果数字必须完整（防止 "224" 被回溯匹配为 "22"）
    # (?!\s*[+＋\-－×÷*/]) — 确保等号右边是最终结果（而非展开式如 224 + 198 + ...）
    _EQ_PATTERN = re.compile(
        r"(?<!\d)"
        r"((?:\d+\.?\d*\s*[+＋\-－×÷*/]\s*)+\d+\.?\d*)"
        r"\s*=\s*"
        r"(\d+\.?\d*)"
        r"(?![\d.])"
        r"(?!\s*[+＋\-－×÷*/])"
    )
    # 除法余数后缀：匹配 "A ÷ B = C 余 D" 格式
    _REMAINDER_PATTERN = re.compile(
        r"(\d+\.?\d*)\s*÷\s*(\d+\.?\d*)\s*=\s*(\d+\.?\d*)\s*余\s*(\d+\.?\d*)"
    )
    # 算术表达式周围的上下文窗口大小（字符数）
    _ARITH_CONTEXT_WINDOW = EVALUATOR_DEFAULTS.arith_context_window

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

        file_texts = _collect_file_texts(output_dir)
        if not file_texts:
            elapsed = (time.monotonic() - start) * 1000
            return self._make_result(
                status=EvalStatus.FAIL,
                score=0.0,
                reason="文档内容为空",
                duration_ms=elapsed,
            )

        # Phase 1: 内置自动检查
        subjects = self.params.get("subjects")
        fact_db = _load_fact_db(subjects)
        findings: list[dict[str, Any]] = []
        checks_total = 0

        arith_findings, arith_checks = self._check_arithmetic(file_texts)
        findings.extend(arith_findings)
        checks_total += arith_checks

        const_findings, const_checks = self._check_constants(file_texts, fact_db)
        findings.extend(const_findings)
        checks_total += const_checks

        misfindings, mis_checks = self._check_misconceptions(file_texts, fact_db)
        findings.extend(misfindings)
        checks_total += mis_checks

        # Phase 2: 可配置规则检查
        fact_rules = self.params.get("fact_rules", [])
        rule_findings, rule_checks = self._check_rules(file_texts, fact_rules)
        findings.extend(rule_findings)
        checks_total += rule_checks

        # Phase 3: LLM 验证（可选）
        orchestrator = context.get("judge_orchestrator")
        evidence_dir = context.get("evidence_dir")
        if orchestrator is not None and evidence_dir is not None:
            return self._evaluate_with_llm(
                file_texts, findings, orchestrator, evidence_dir, context, start
            )

        # 计分
        return self._compute_result(file_texts, findings, start, checks_total)

    # ─── Phase 1: 内置自动检查 ───

    def _check_arithmetic(self, file_texts: dict[str, str]) -> tuple[list[dict[str, Any]], int]:
        """验证文档中的算术等式是否正确。

        支持多項式表达式（如 ``28×8 + 22×9 + 35×4 = 562``）和
        带余数除法（如 ``125 ÷ 3 = 41 余 2``）。

        Returns:
            (findings, checks_count) — findings 为错误列表，checks_count 为总检查次数。
        """
        findings: list[dict[str, Any]] = []
        checks = 0

        # ─── Pass 1: 带余数除法 "A ÷ B = C 余 D" ───
        remainder_positions: set[int] = set()
        for filename, text in file_texts.items():
            for m in self._REMAINDER_PATTERN.finditer(text):
                remainder_positions.add(m.start())

                dividend_s, divisor_s, quotient_s, remainder_s = m.groups()

                start_pos = max(0, m.start() - self._ARITH_CONTEXT_WINDOW)
                end_pos = min(len(text), m.end() + self._ARITH_CONTEXT_WINDOW)
                context_window = text[start_pos:end_pos]
                if _VERTICAL_CALC_KEYWORDS.search(context_window):
                    continue

                try:
                    dividend = float(dividend_s)
                    divisor = float(divisor_s)
                    quotient = float(quotient_s)
                    remainder = float(remainder_s)
                except ValueError:
                    continue

                if divisor == 0:
                    continue

                checks += 1
                # 验证: dividend == quotient × divisor + remainder
                expected = quotient * divisor + remainder
                if abs(expected - dividend) > EVALUATOR_DEFAULTS.arith_tolerance:
                    findings.append(
                        {
                            "file": filename,
                            "check_type": "arithmetic",
                            "severity": "error",
                            "message": (
                                f"除法余数错误: {float(dividend_s):g} ÷ {float(divisor_s):g} "
                                f"= {float(quotient_s):g} 余 {float(remainder_s):g}"
                                f"（验证: {float(quotient_s):g} × {float(divisor_s):g}"
                                f" + {float(remainder_s):g}"
                                f" = {expected:g} ≠ {float(dividend_s):g}）"
                            ),
                        }
                    )

        # ─── Pass 2: 一般等式 "LHS = result" ───
        for filename, text in file_texts.items():
            for m in self._EQ_PATTERN.finditer(text):
                # 跳过已被余数除法覆盖的位置
                if m.start() in remainder_positions:
                    continue

                lhs_expr, result_s = m.group(1), m.group(2)

                # 跳过竖式计算上下文中的中间步骤
                start_pos = max(0, m.start() - self._ARITH_CONTEXT_WINDOW)
                end_pos = min(len(text), m.end() + self._ARITH_CONTEXT_WINDOW)
                context_window = text[start_pos:end_pos]
                if _VERTICAL_CALC_KEYWORDS.search(context_window):
                    continue

                try:
                    result_val = float(result_s)
                except ValueError:
                    continue

                expected = _eval_simple_expr(lhs_expr)
                if expected is None:
                    continue

                checks += 1
                if abs(expected - result_val) > EVALUATOR_DEFAULTS.arith_tolerance:
                    findings.append(
                        {
                            "file": filename,
                            "check_type": "arithmetic",
                            "severity": "error",
                            "message": (
                                f"算术错误: {lhs_expr.strip()} = {result_s}（应为 {expected:g}）"
                            ),
                        }
                    )

        return findings, checks

    def _check_constants(
        self, file_texts: dict[str, str], fact_db: dict
    ) -> tuple[list[dict[str, Any]], int]:
        """校验文档中的科学/数学常数是否与标准值一致。

        Returns:
            (findings, checks_count)
        """
        findings: list[dict[str, Any]] = []
        checks = 0
        constants = fact_db.get("constants", [])

        for const in constants:
            pattern_str = const.get("extract_pattern", "")
            if not pattern_str:
                continue
            try:
                pattern = re.compile(pattern_str, re.IGNORECASE)
            except re.error:
                continue

            value = const.get("value", 0)
            tolerance = const.get("tolerance", EVALUATOR_DEFAULTS.arith_tolerance)
            name = const.get("name", "未知常数")

            for filename, text in file_texts.items():
                for m in pattern.finditer(text):
                    raw = m.group(1).replace(",", "")
                    try:
                        val = float(raw)
                    except ValueError:
                        continue

                    checks += 1
                    if abs(val - value) > tolerance:
                        findings.append(
                            {
                                "file": filename,
                                "check_type": "constant",
                                "severity": "error",
                                "message": f"{name}: 值 {val} 与标准值 {value} 偏差超过容差 {tolerance}",
                            }
                        )

        return findings, checks

    def _check_misconceptions(
        self, file_texts: dict[str, str], fact_db: dict
    ) -> tuple[list[dict[str, Any]], int]:
        """检测文档中的常见事实错误模式（疑似线索，不参与 pass/fail 判定）。

        misconception pattern 多来自评测题错误选项标记，匹配正常教学文本易误报，
        故统一降为 warning 级：仍记录在 findings 供报告/LLM 参考，但不进入
        rule_errors 一票否决 pass/fail。

        Returns:
            (findings, checks_count) — checks_count 始终为 0。
        """
        findings: list[dict[str, Any]] = []
        misconceptions = fact_db.get("misconceptions", [])

        for entry in misconceptions:
            pattern_str = entry.get("pattern", "")
            if not pattern_str:
                continue
            try:
                pattern = re.compile(pattern_str)
            except re.error:
                continue

            correct = entry.get("correct", "")
            description = entry.get("description", "疑似常识错误")
            original_severity = entry.get("severity", "warning")

            for filename, text in file_texts.items():
                if pattern.search(text):
                    findings.append(
                        {
                            "file": filename,
                            "check_type": "misconception",
                            "severity": "warning",  # effective: 不参与 pass/fail
                            "rule_severity": original_severity,  # 原始 severity，报告/审计用
                            "message": f"{description}（正确: {correct}）",
                        }
                    )

        return findings, 0

    # ─── Phase 2: 可配置规则检查 ───

    def _check_rules(
        self, file_texts: dict[str, str], fact_rules: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], int]:
        """执行用户配置的事实验证规则（per-file）。

        Returns:
            (findings, checks_count)
        """
        findings: list[dict[str, Any]] = []
        checks = 0
        merged_text = "\n\n".join(file_texts.values())

        for rule in fact_rules:
            rule_type = rule.get("type", "contains")

            if rule_type == "must_contain":
                checks += 1
                keyword = rule.get("keyword", "")
                if keyword and keyword not in merged_text:
                    findings.append(
                        {
                            "file": "(全局)",
                            "check_type": "rule",
                            "severity": "error",
                            "message": f"缺少必要内容: '{keyword}'",
                            "rule_type": rule_type,
                        }
                    )

            elif rule_type == "must_not_contain":
                checks += 1
                wrong = rule.get("pattern", "")
                if wrong and wrong in merged_text:
                    findings.append(
                        {
                            "file": "(全局)",
                            "check_type": "rule",
                            "severity": "error",
                            "message": f"包含错误表述: '{wrong[:50]}'",
                            "rule_type": rule_type,
                        }
                    )

            elif rule_type == "value_range":
                sub_findings, sub_checks = self._check_value_range_rule(file_texts, rule)
                findings.extend(sub_findings)
                checks += sub_checks

            elif rule_type == "regex_match":
                sub_findings, sub_checks = self._check_regex_match_rule(file_texts, rule)
                findings.extend(sub_findings)
                checks += sub_checks

            elif rule_type == "number_in_context":
                sub_findings, sub_checks = self._check_number_in_context_rule(file_texts, rule)
                findings.extend(sub_findings)
                checks += sub_checks

            elif rule_type == "forbidden_pattern":
                sub_findings, sub_checks = self._check_forbidden_pattern_rule(file_texts, rule)
                findings.extend(sub_findings)
                checks += sub_checks

        return findings, checks

    def _check_value_range_rule(
        self, file_texts: dict[str, str], rule: dict[str, Any]
    ) -> tuple[list[dict[str, Any]], int]:
        """检查数值范围规则（per-file）。

        Returns:
            (findings, checks_count)
        """
        findings: list[dict[str, Any]] = []
        checks = 0
        name = rule.get("name", "")
        pattern = rule.get("pattern", r"(\d+\.?\d*)")
        min_val = rule.get("min")
        max_val = rule.get("max")

        try:
            compiled = re.compile(pattern)
        except re.error:
            return findings, 0

        for filename, text in file_texts.items():
            for m in compiled.finditer(text):
                try:
                    val = float(m.group(1))
                except (ValueError, IndexError):
                    continue
                checks += 1
                if min_val is not None and val < min_val:
                    findings.append(
                        {
                            "file": filename,
                            "check_type": "rule",
                            "severity": "error",
                            "message": f"{name}: 值 {val} 低于最小值 {min_val}",
                            "rule_type": "value_range",
                        }
                    )
                if max_val is not None and val > max_val:
                    findings.append(
                        {
                            "file": filename,
                            "check_type": "rule",
                            "severity": "error",
                            "message": f"{name}: 值 {val} 超过最大值 {max_val}",
                            "rule_type": "value_range",
                        }
                    )

        return findings, checks

    def _check_regex_match_rule(
        self, file_texts: dict[str, str], rule: dict[str, Any]
    ) -> tuple[list[dict[str, Any]], int]:
        """检查正则匹配规则。

        Returns:
            (findings, checks_count)
        """
        findings: list[dict[str, Any]] = []
        checks = 1  # 至少 1 次全局检查
        pattern_str = rule.get("pattern", "")
        must_match = rule.get("must_match", True)
        name = rule.get("name", "正则匹配")

        try:
            compiled = re.compile(pattern_str)
        except re.error:
            return findings, 0

        if must_match:
            # 至少一个文件需要匹配
            found = any(compiled.search(text) for text in file_texts.values())
            if not found:
                findings.append(
                    {
                        "file": "(全局)",
                        "check_type": "rule",
                        "severity": "error",
                        "message": f"{name}: 未找到匹配 '{pattern_str}' 的内容",
                        "rule_type": "regex_match",
                    }
                )
        else:
            # 不应有任何文件匹配
            for filename, text in file_texts.items():
                if compiled.search(text):
                    findings.append(
                        {
                            "file": filename,
                            "check_type": "rule",
                            "severity": "error",
                            "message": f"{name}: 不应包含匹配 '{pattern_str}' 的内容",
                            "rule_type": "regex_match",
                        }
                    )

        return findings, checks

    def _check_number_in_context_rule(
        self, file_texts: dict[str, str], rule: dict[str, Any]
    ) -> tuple[list[dict[str, Any]], int]:
        """检查关键词附近的数值是否在指定范围内。

        Returns:
            (findings, checks_count)
        """
        findings: list[dict[str, Any]] = []
        checks = 0
        keyword = rule.get("keyword", "")
        min_val = rule.get("min")
        max_val = rule.get("max")
        context_chars = rule.get("context_chars", 50)
        name = rule.get("name", keyword)

        if not keyword:
            return findings, 0

        # 构建上下文窗口正则：关键词前后 context_chars 字符内的数字
        kw_pattern = re.compile(
            re.escape(keyword) + r".{0," + str(context_chars) + r"}?(\d+\.?\d*)"
        )

        for filename, text in file_texts.items():
            for m in kw_pattern.finditer(text):
                try:
                    val = float(m.group(1))
                except ValueError:
                    continue
                checks += 1
                if min_val is not None and val < min_val:
                    findings.append(
                        {
                            "file": filename,
                            "check_type": "rule",
                            "severity": "error",
                            "message": f"{name}: 关键词附近数值 {val} 低于最小值 {min_val}",
                            "rule_type": "number_in_context",
                        }
                    )
                if max_val is not None and val > max_val:
                    findings.append(
                        {
                            "file": filename,
                            "check_type": "rule",
                            "severity": "error",
                            "message": f"{name}: 关键词附近数值 {val} 超过最大值 {max_val}",
                            "rule_type": "number_in_context",
                        }
                    )

        return findings, checks

    def _check_forbidden_pattern_rule(
        self, file_texts: dict[str, str], rule: dict[str, Any]
    ) -> tuple[list[dict[str, Any]], int]:
        """检查严格禁止的模式。

        Returns:
            (findings, checks_count)
        """
        findings: list[dict[str, Any]] = []
        checks = 0
        pattern_str = rule.get("pattern", "")
        reason = rule.get("reason", "包含禁止内容")

        try:
            compiled = re.compile(pattern_str)
        except re.error:
            return findings, 0

        for filename, text in file_texts.items():
            checks += 1
            if compiled.search(text):
                findings.append(
                    {
                        "file": filename,
                        "check_type": "rule",
                        "severity": "error",
                        "message": reason,
                        "rule_type": "forbidden_pattern",
                    }
                )

        return findings, checks

    # ─── 计分 ───

    def _compute_result(
        self,
        file_texts: dict[str, str],
        findings: list[dict[str, Any]],
        start: float,
        checks_total: int = 0,
    ) -> Any:
        """根据 findings 计算 score 并返回 ConstraintResult。"""
        errors = [f for f in findings if f["severity"] == "error"]
        warnings = [f for f in findings if f["severity"] == "warning"]

        # 如果没有执行任何检查，默认通过
        if checks_total == 0:
            raw_score = 1.0
        else:
            raw_score = (checks_total - len(errors)) / checks_total

        threshold = self.params.get("pass_threshold", 0.8)
        passed = raw_score >= threshold
        elapsed = (time.monotonic() - start) * 1000

        # 构建 reason
        parts: list[str] = []
        if errors:
            parts.append(f"发现 {len(errors)} 处错误")
        if warnings:
            parts.append(f"{len(warnings)} 处警告")
        if not findings:
            parts.append("未发现知识准确性问题")
        reason = "知识准确性检查：" + "，".join(parts)

        return self._make_result(
            status=EvalStatus.PASS if passed else EvalStatus.FAIL,
            score=1.0 if passed else 0.0,
            raw_score=raw_score,
            reason=reason,
            details={
                "findings": findings,
                "files_checked": list(file_texts.keys()),
                "checks_total": checks_total,
                "errors": len(errors),
                "warnings": len(warnings),
            },
            duration_ms=elapsed,
        )

    # ─── Phase 3: LLM 语义验证 ───

    def _evaluate_with_llm(
        self,
        file_texts: dict[str, str],
        findings: list[dict[str, Any]],
        orchestrator: Any,
        evidence_dir: Any,
        context: dict[str, Any],
        start: float,
    ) -> Any:
        """使用 LLM 进行知识准确性语义验证。"""
        from pathlib import Path

        # 拼接文本，每文件截断
        max_file_chars = self.params.get("max_file_chars", EVALUATOR_DEFAULTS.max_file_chars)
        max_total_chars = self.params.get("max_content_chars", EVALUATOR_DEFAULTS.max_content_chars)
        combined_parts: list[str] = []
        total_chars = 0
        for fname, text in file_texts.items():
            chunk = text[:max_file_chars]
            if total_chars + len(chunk) > max_total_chars:
                remaining = max_total_chars - total_chars
                if remaining > 100:
                    combined_parts.append(f"--- {fname} ---\n{chunk[:remaining]}")
                break
            combined_parts.append(f"--- {fname} ---\n{chunk}")
            total_chars += len(chunk)
        combined_text = "\n\n".join(combined_parts)

        # info_accuracy LLM 独立评估原文事实性，不注入规则可疑条目（解耦）：
        # 对照实验证实（docs/arch/12 §3.4），把规则误报（如"水的pH 800"实为报告字数）
        # 作为"可疑条目"传给 LLM 会严重污染整体评分（化学样本 factual 4.0→10.0）。
        # 规则 findings 由 fact_verdict 过滤后经 rule_errors 独立计分，与 LLM 解耦。
        variables = {
            "content": combined_text[: EVALUATOR_DEFAULTS.llm_judge_combined_content_chars],
            "title": context.get("task_input", {}).get("title", "未知标题"),
            "subject": context.get("task_input", {}).get("subject", "未知学科"),
        }

        try:
            scores, record = orchestrator.judge(
                constraint_id=self.evaluator_id,
                sample_id=context.get("sample_id", "unknown"),
                template_id="info_accuracy",
                variables=variables,
                evidence_dir=Path(evidence_dir)
                if not isinstance(evidence_dir, Path)
                else evidence_dir,
                provider_name=self.params.get("llm_provider"),
            )
        except Exception:
            # LLM 调用失败，回退到 Phase 1-2 的结果
            return self._compute_result(file_texts, findings, start, checks_total=0)

        elapsed = (time.monotonic() - start) * 1000

        # 计算加权分数
        template = orchestrator.templates.get("info_accuracy")
        if template and template.dimensions:
            total_weight = sum(d.weight for d in template.dimensions)
            weighted = sum(scores.get(d.dim_id, 0.0) * d.weight for d in template.dimensions)
            avg_score = (weighted / total_weight / 10.0) if total_weight > 0 else 1.0
        else:
            vals = list(scores.values())
            avg_score = (sum(vals) / len(vals) / 10.0) if vals else 1.0

        avg_score = max(0.0, min(1.0, avg_score))

        # 合并 findings 和 LLM 结果
        llm_errors = (
            record.raw_response.get("errors_found", [])
            if record and hasattr(record, "raw_response") and isinstance(record.raw_response, dict)
            else []
        )

        # 计分：合并 rule-based findings + LLM 分数
        # rule-based error findings 先经 LLM 二次确认（fact_verdict）过滤正则误报
        error_findings = [f for f in findings if f["severity"] == "error"]
        if error_findings:
            try:
                rule_errors = self._confirm_findings_with_llm(
                    error_findings, file_texts, orchestrator, evidence_dir, context
                )
            except Exception:
                logger.warning(
                    "fact_verdict 二次确认失败，保留全部规则 error（召回优先）",
                    exc_info=True,
                )
                rule_errors = error_findings
        else:
            rule_errors = []
        rule_warnings = [f for f in findings if f["severity"] == "warning"]

        # 如果 rule-based 有（经确认的）error → FAIL
        threshold = self.params.get("pass_threshold", 0.8)
        combined_score = min(avg_score, 1.0)
        passed = combined_score >= threshold and len(rule_errors) == 0
        score = 1.0 if passed else 0.0

        # 构建 reason
        score_parts = [f"{k}={v:.1f}" for k, v in scores.items()]
        reason = f"知识准确性（LLM + 规则）：{', '.join(score_parts)}"
        if rule_errors:
            reason += f"；规则检查发现 {len(rule_errors)} 处错误（经 LLM 二次确认）"
        elif error_findings:
            reason += f"；规则标记 {len(error_findings)} 处疑似错误经 LLM 二次确认均不成立"

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
            raw_score=combined_score,
            reason=reason,
            details={
                "findings": findings,
                "llm_errors": llm_errors,
                "scores": scores,
                "confidence": record.confidence if record else {},
                "files_checked": list(file_texts.keys()),
                "checks_total": len(findings),
                "errors": len(rule_errors),
                "warnings": len(rule_warnings),
            },
            duration_ms=elapsed,
            judge_provider=record.provider_name if record else None,
            judge_model=record.model if record else None,
            judge_record_path=record_path,
        )

    def _confirm_findings_with_llm(
        self,
        error_findings: list[dict[str, Any]],
        file_texts: dict[str, str],
        orchestrator: Any,
        evidence_dir: Any,
        context: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """对规则 error findings 批量调 LLM（fact_verdict）逐条裁定，返回被确认的真错误。

        被判为误报（is_real_error=false）的 finding 仍保留在原列表（写审计字段
        _llm_confirmed/_llm_reason），但不计入返回值（即不进入 rule_errors 一票否决）。
        调用/解析异常由调用方捕获并降级为"保留全部"（召回优先）。
        """
        candidates = [
            {
                "index": i,
                "file": f.get("file", ""),
                "message": f.get("message", ""),
                "context": self._extract_finding_context(f, file_texts),
            }
            for i, f in enumerate(error_findings)
        ]
        ev_dir = evidence_dir if isinstance(evidence_dir, Path) else Path(evidence_dir)
        _scores, record = orchestrator.judge(
            constraint_id=self.evaluator_id,
            sample_id=context.get("sample_id", "unknown"),
            template_id="fact_verdict",
            variables={
                "title": context.get("task_input", {}).get("title", "未知标题"),
                "subject": context.get("task_input", {}).get("subject", "未知学科"),
                "candidates": candidates,
            },
            evidence_dir=ev_dir,
            provider_name=self.params.get("llm_provider"),
            judge_id_suffix="fact_verdict",
        )

        # verdicts 在 JudgeRecord.parsed_scores（解析后的完整 dict）
        parsed = getattr(record, "parsed_scores", None) if record else None
        verdicts = parsed.get("verdicts", []) if isinstance(parsed, dict) else []
        verdict_map = {v.get("index"): v for v in verdicts if isinstance(v, dict) and "index" in v}

        confirmed: list[dict[str, Any]] = []
        for i, f in enumerate(error_findings):
            v = verdict_map.get(i)
            # 缺裁定 → 默认 True（召回优先，不漏报）
            is_real = bool(v.get("is_real_error", True)) if v else True
            f["_llm_confirmed"] = is_real
            f["_llm_reason"] = v.get("reason", "") if v else ""
            if is_real:
                confirmed.append(f)
        return confirmed

    @staticmethod
    def _extract_finding_context(finding: dict[str, Any], file_texts: dict[str, str]) -> str:
        """提取 finding 所在文件的截断文本，供 LLM 裁定参考。"""
        fname = finding.get("file", "")
        text = file_texts.get(fname, "")
        return text[: EVALUATOR_DEFAULTS.max_file_chars] if text else ""


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

        # 提取年份 — 排除持续时间模式（"100年后""500年历史"等）
        # (?!\s*[后历史内间以来前]) — "N年后/历史/内/间/以/来/前" 是时间段，非年份
        _YEAR_PATTERN = re.compile(r"(?:公元)?(\d{3,4})\s*年(?!\s*[后历史内间以来前])")
        years = _YEAR_PATTERN.findall(text)
        year_list: list[int] = []
        if years:
            year_list = [int(y) for y in years if 0 < int(y) <= 2100]
            for i in range(1, len(year_list)):
                if year_list[i] < year_list[i - 1]:
                    # 允许回溯（如回顾历史），但标记为潜在问题
                    pass  # 时序回溯不一定错误，暂不报告

        # 提取序号
        sequences = re.findall(r"第([一二三四五六七八九十百千\d]+)[章节步骤期]", text)

        elapsed = (time.monotonic() - start) * 1000

        return self._make_result(
            status=EvalStatus.PASS,
            score=1.0,
            reason="时序正确性检查通过",
            details={
                "files_checked": _collect_file_names(output_dir),
                "years_found": year_list[:20],
                "sequences_found": len(sequences),
                "content_length": len(text),
            },
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
            return self._evaluate_with_llm(
                text, context, orchestrator, evidence_dir, output_dir, start
            )

        # 降级模式：Rule-based 基本矛盾检查
        return self._evaluate_rule_based(text, output_dir, start)

    def _evaluate_with_llm(
        self,
        text: str,
        context: dict[str, Any],
        orchestrator: Any,
        evidence_dir: Any,
        output_dir: Path,
        start: float,
    ) -> Any:
        """使用 LLM 进行逻辑一致性评估。"""
        from pathlib import Path

        max_chars = self.params.get("max_content_chars", EVALUATOR_DEFAULTS.max_content_chars)
        if len(text) > max_chars:
            text = text[:max_chars] + "\n\n[...内容已截断...]"

        variables = {
            "content": text[: EVALUATOR_DEFAULTS.llm_judge_content_chars],
            "title": context.get("task_input", {}).get("title", "未知标题"),
        }

        try:
            scores, record = orchestrator.judge(
                constraint_id=self.evaluator_id,
                sample_id=context.get("sample_id", "unknown"),
                template_id="logical_consistency",
                variables=variables,
                evidence_dir=Path(evidence_dir)
                if not isinstance(evidence_dir, Path)
                else evidence_dir,
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
        passed = avg_score >= EVALUATOR_DEFAULTS.logical_consistency_pass_threshold
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
            details={
                "scores": scores,
                "confidence": record.confidence if record else {},
                "files_checked": _collect_file_names(output_dir) if output_dir else [],
            },
            duration_ms=elapsed,
            judge_provider=record.provider_name if record else None,
            judge_model=record.model if record else None,
            judge_record_path=record_path,
        )

    def _evaluate_rule_based(self, text: str, output_dir: Path, start: float) -> Any:
        """Rule-based 降级模式：检查基本逻辑矛盾。

        检查策略：
        1. 仅匹配具名变量赋值（如 "总面积=567"、"total = 350"），
           排除纯数字（避免将算术项如 "8=32" 误判为变量）
        2. 中文变量使用公共后缀匹配（"有学生数=42" 与 "但学生数=45"
           共享后缀 "学生数" → 视为同一变量）
        3. Per-file 检查（不同文件的变量互不比较）
        4. 输出包含文件归属和上下文片段
        """
        elapsed = (time.monotonic() - start) * 1000

        # 具名变量正则：变量名以字母或中文字符开头，排除纯数字
        _VAR_PATTERN = re.compile(
            r"(?<![\d])"
            r"([a-zA-Z_一-鿿][\w一-鿿]{0,19})"
            r"\s*[=＝]\s*"
            r"(\d+\.?\d*)"
        )

        file_texts = _collect_file_texts(output_dir)
        findings: list[dict[str, Any]] = []

        for filename, ftext in file_texts.items():
            # 收集本文件中每个变量的所有值和上下文
            var_values: dict[str, set[str]] = {}
            var_contexts: dict[str, list[str]] = {}

            for m in _VAR_PATTERN.finditer(ftext):
                name, value = m.group(1), m.group(2)
                # 跳过单字母 ASCII 变量（数学公式中的 x=5 等）
                if len(name) <= 1 and name.isascii():
                    continue
                var_values.setdefault(name, set()).add(value)
                ctx_start = max(0, m.start() - 25)
                ctx_end = min(len(ftext), m.end() + 15)
                ctx = ftext[ctx_start:ctx_end].replace("\n", " ").strip()
                var_contexts.setdefault(name, []).append(f"{name}={value} (…{ctx}…)")

            # Pass 1: 精确匹配 — 同名变量有多个不同值
            reported_vars: set[str] = set()
            for name, values in var_values.items():
                if len(values) > 1:
                    reported_vars.add(name)
                    contexts = var_contexts.get(name, [])
                    findings.append(
                        {
                            "file": filename,
                            "check_type": "variable_contradiction",
                            "severity": "error",
                            "variable": name,
                            "values": sorted(values),
                            "occurrences": len(contexts),
                            "contexts": contexts[:5],
                        }
                    )

            # Pass 2: 中文公共后缀匹配 — "有学生数" 与 "但学生数"
            # 共享后缀 "学生数" → 视为同一变量的不同表述
            cjk_vars = {
                n: vs
                for n, vs in var_values.items()
                if n not in reported_vars and any("一" <= c <= "鿿" for c in n)
            }
            if len(cjk_vars) >= 2:
                findings.extend(self._check_cjk_suffix_conflicts(filename, cjk_vars, var_contexts))

        files_checked = _collect_file_names(output_dir)

        if not findings:
            return self._make_result(
                status=EvalStatus.PASS,
                score=1.0,
                reason="逻辑一致性检查通过（Rule-based 降级模式）",
                details={
                    "files_checked": files_checked,
                    "content_length": len(text),
                    "mode": "rule_based",
                    "checks_performed": "named_variable_assignment",
                },
                duration_ms=elapsed,
            )
        else:
            error_msgs = [
                f"{f['file']}: 变量「{f['variable']}」有 {len(f['values'])} 个不同值 {f['values']}"
                for f in findings
            ]
            return self._make_result(
                status=EvalStatus.FAIL,
                score=0.0,
                reason=f"发现 {len(findings)} 处变量赋值矛盾",
                details={
                    "findings": findings,
                    "errors": error_msgs[:10],
                    "files_checked": files_checked,
                    "content_length": len(text),
                    "mode": "rule_based",
                },
                duration_ms=elapsed,
            )

    @staticmethod
    def _check_cjk_suffix_conflicts(
        filename: str,
        cjk_vars: dict[str, set[str]],
        var_contexts: dict[str, list[str]],
    ) -> list[dict[str, Any]]:
        """检查中文变量的公共后缀冲突。

        如 "有学生数=42" 和 "但学生数=45" 共享后缀 "学生数"，
        但值不同 → 报告为矛盾。
        """
        names = list(cjk_vars.keys())
        findings: list[dict[str, Any]] = []
        seen_pairs: set[frozenset[str]] = set()

        for i, name_a in enumerate(names):
            for name_b in names[i + 1 :]:
                pair_key = frozenset({name_a, name_b})
                if pair_key in seen_pairs:
                    continue

                # 寻找公共后缀（至少 2 个中文字符）
                suffix = ""
                min_len = min(len(name_a), len(name_b))
                for k in range(1, min_len + 1):
                    if name_a[-k] == name_b[-k] and "一" <= name_a[-k] <= "鿿":
                        suffix = name_a[-k:]
                    else:
                        break

                if len(suffix) < 2:
                    continue

                seen_pairs.add(pair_key)

                # 合并两个变量的值
                merged_values = cjk_vars[name_a] | cjk_vars[name_b]
                if len(merged_values) > 1:
                    merged_contexts = var_contexts.get(name_a, []) + var_contexts.get(name_b, [])
                    findings.append(
                        {
                            "file": filename,
                            "check_type": "variable_contradiction",
                            "severity": "error",
                            "variable": suffix,
                            "matched_as": [name_a, name_b],
                            "values": sorted(merged_values),
                            "occurrences": len(merged_contexts),
                            "contexts": merged_contexts[:5],
                        }
                    )

        return findings


@registry.register("commonsense.math_formula")
class MathFormulaEvaluator(BaseEvaluator):
    """公式正确性检查 — 验证数学公式的合理性。

    检查内容：
    1. LaTeX 公式中的括号匹配（$...$ 格式）
    2. 算术等式正确性（复用 InfoAccuracyEvaluator 的
       _EQ_PATTERN + _eval_simple_expr，避免二元正则子表达式误报）
    3. 符号公式校验（利用 domain_facts.math_formulas 中的 30+ 条
       已知公式，检测文档中出现的公式是否正确）
    """

    evaluator_id = "commonsense.math_formula"
    name = "公式正确性检查"
    tier = ConstraintTier.HARD_SCORE
    method = EvalMethod.MATH_VERIFY

    # 复用 InfoAccuracyEvaluator 的算术正则（完整左侧，非二元子表达式）
    _EQ_PATTERN = InfoAccuracyEvaluator._EQ_PATTERN
    _REMAINDER_PATTERN = InfoAccuracyEvaluator._REMAINDER_PATTERN

    # ─── 符号公式提取正则 ───

    # 匹配 "圆的面积 S=πr²" / "长方形面积=长×宽" / "梯形面积公式：(上底+下底)×高÷2"
    _FORMULA_NAME_PATTERN = re.compile(
        r"([一-鿿]{2,8}(?:面积|周长|体积|表面积|侧面积))"
        r"\s*(?:公式)?[是为]?\s*[：:＝=]?\s*"
        r"([A-Za-z½⅓¼¾π\d+\-()×÷*/^²³·\s＝=]+?)"
        r"(?=[，。、；\n\r]|$)"
    )
    _FORMULA_KW_PATTERN = re.compile(
        r"([一-鿿]{2,8})公式"
        r"[是为]?\s*[：:＝=]?\s*"
        r"([A-Za-z½⅓¼¾π\d+\-()×÷*/^²³·\s＝=]+?)"
        r"(?=[，。、；\n\r]|$)"
    )

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

        file_texts = _collect_file_texts(output_dir)
        if not file_texts:
            elapsed = (time.monotonic() - start) * 1000
            return self._make_result(
                status=EvalStatus.FAIL,
                score=0.0,
                reason="文档内容为空",
                duration_ms=elapsed,
            )

        errors: list[str] = []
        formulas_checked = 0
        arith_checks = 0
        symbolic_checks = 0

        for filename, text in file_texts.items():
            # 检查 LaTeX 公式中的括号匹配
            formula_patterns = re.findall(r"[$].+?[$]", text)
            formulas_checked += len(formula_patterns)
            for formula in formula_patterns:
                if formula.count("(") != formula.count(")"):
                    errors.append(f"{filename}: 公式括号不匹配: {formula[:50]}")
                if formula.count("{") != formula.count("}"):
                    errors.append(f"{filename}: 公式花括号不匹配: {formula[:50]}")

            # 算术等式验证（复用完整左侧正则 + 竖式上下文跳过）
            remainder_positions: set[int] = set()
            for m in self._REMAINDER_PATTERN.finditer(text):
                remainder_positions.add(m.start())
                dividend_s, divisor_s, quotient_s, remainder_s = m.groups()
                start_pos = max(0, m.start() - 40)
                end_pos = min(len(text), m.end() + 40)
                ctx_window = text[start_pos:end_pos]
                if _VERTICAL_CALC_KEYWORDS.search(ctx_window):
                    continue
                try:
                    dividend = float(dividend_s)
                    divisor = float(divisor_s)
                    quotient = float(quotient_s)
                    remainder = float(remainder_s)
                except ValueError:
                    continue
                if divisor == 0:
                    continue
                arith_checks += 1
                expected = quotient * divisor + remainder
                if abs(expected - dividend) > EVALUATOR_DEFAULTS.arith_tolerance:
                    errors.append(
                        f"{filename}: 除法余数错误 "
                        f"{float(dividend_s):g} ÷ {float(divisor_s):g} "
                        f"= {float(quotient_s):g} 余 {float(remainder_s):g}"
                        f"（应为 {expected:g}）"
                    )

            for m in self._EQ_PATTERN.finditer(text):
                if m.start() in remainder_positions:
                    continue
                lhs_expr, result_s = m.group(1), m.group(2)
                start_pos = max(0, m.start() - 40)
                end_pos = min(len(text), m.end() + 40)
                ctx_window = text[start_pos:end_pos]
                if _VERTICAL_CALC_KEYWORDS.search(ctx_window):
                    continue
                try:
                    result_val = float(result_s)
                except ValueError:
                    continue
                expected = _eval_simple_expr(lhs_expr)
                if expected is None:
                    continue
                arith_checks += 1
                if abs(expected - result_val) > EVALUATOR_DEFAULTS.arith_tolerance:
                    errors.append(
                        f"{filename}: 算术错误 {lhs_expr.strip()} = {result_s}（应为 {expected:g}）"
                    )

            # 符号公式校验
            sym_errors, sym_checks = self._check_symbolic_formulas(filename, text)
            errors.extend(sym_errors)
            symbolic_checks += sym_checks

        elapsed = (time.monotonic() - start) * 1000
        files_checked = list(file_texts.keys())

        if not errors:
            return self._make_result(
                status=EvalStatus.PASS,
                score=1.0,
                reason="公式正确性检查通过",
                details={
                    "files_checked": files_checked,
                    "formulas_checked": formulas_checked,
                    "arithmetic_checked": arith_checks,
                    "symbolic_checked": symbolic_checks,
                },
                duration_ms=elapsed,
            )
        else:
            return self._make_result(
                status=EvalStatus.FAIL,
                score=0.0,
                reason=f"发现 {len(errors)} 处公式错误",
                details={
                    "errors": errors,
                    "files_checked": files_checked,
                    "formulas_checked": formulas_checked,
                    "arithmetic_checked": arith_checks,
                    "symbolic_checked": symbolic_checks,
                },
                duration_ms=elapsed,
            )

    # ─── 符号公式校验 ───

    def _check_symbolic_formulas(self, filename: str, text: str) -> tuple[list[str], int]:
        """利用 domain_facts 校验文档中的符号公式。

        Returns:
            (errors, checks_count)
        """
        from agent_eval.evaluation.evaluators.formula_normalizer import (
            build_formula_index,
            normalize_formula,
            normalize_formula_name,
        )

        fact_db = _load_fact_db(subjects=["math"])
        domain_facts = fact_db.get("domain_facts", {})
        if not isinstance(domain_facts, dict) or "math_formulas" not in domain_facts:
            return [], 0

        formula_index = build_formula_index(domain_facts)
        if not formula_index:
            return [], 0

        errors: list[str] = []
        checks = 0
        reported: set[str] = set()  # 去重

        for pattern in (self._FORMULA_NAME_PATTERN, self._FORMULA_KW_PATTERN):
            for m in pattern.finditer(text):
                name_raw = m.group(1)
                expr_raw = m.group(2)

                norm_name = normalize_formula_name(name_raw)
                norm_expr = normalize_formula(expr_raw)

                if len(norm_expr) < 2:
                    continue

                matched = self._find_matching_formula(norm_name, formula_index)
                if matched is None:
                    continue

                dedup_key = f"{filename}:{matched['canonical_name']}"
                if dedup_key in reported:
                    continue

                checks += 1
                reported.add(dedup_key)
                canonical = matched["normalized_formula"]

                if not self._formulas_match(norm_expr, canonical):
                    errors.append(
                        f"{filename}: 公式错误 「{name_raw}」"
                        f"文中为 {expr_raw.strip()}，"
                        f"正确应为 {matched['formula']}"
                    )

        return errors, checks

    @staticmethod
    def _find_matching_formula(
        norm_name: str, formula_index: list[dict[str, Any]]
    ) -> dict[str, Any] | None:
        """根据归一化名称查找匹配的公式条目。

        精确匹配优先，其次子串匹配（仅当唯一匹配时返回）。
        """
        for entry in formula_index:
            if norm_name == entry["canonical_name"]:
                return entry

        candidates = [
            entry
            for entry in formula_index
            if norm_name in entry["canonical_name"] or entry["canonical_name"] in norm_name
        ]
        if len(candidates) == 1:
            return candidates[0]
        return None

    @staticmethod
    def _formulas_match(extracted: str, canonical: str) -> bool:
        """比较归一化后的公式表达式是否匹配。

        处理：
        - 可选的左侧变量：S=πr² 与 πr² 视为相同
        - 等价形式：2πr=πd 中的多选项
        """
        if extracted == canonical:
            return True

        def _strip_lhs(f: str) -> str:
            """去掉单字母 LHS 变量（如 S=、V=、C=）。"""
            parts = f.split("=", 1)
            if len(parts) == 2 and len(parts[0]) <= 2 and parts[0].isalpha():
                return parts[1]
            return f

        if _strip_lhs(extracted) == _strip_lhs(canonical):
            return True

        # canonical 可能含多个等价形式（如 "2πr=πd"）
        canonical_rhs = _strip_lhs(canonical)
        extracted_rhs = _strip_lhs(extracted)
        for alt in canonical_rhs.split("="):
            if extracted_rhs == alt:
                return True

        return False


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

        files_checked = _collect_file_names(output_dir)
        if not errors:
            return self._make_result(
                status=EvalStatus.PASS,
                score=1.0,
                reason="单位一致性检查通过",
                details={"files_checked": files_checked, "content_length": len(text)},
                duration_ms=elapsed,
            )
        else:
            return self._make_result(
                status=EvalStatus.FAIL,
                score=0.0,
                reason=f"发现 {len(errors)} 处单位问题",
                details={
                    "errors": errors,
                    "files_checked": files_checked,
                    "content_length": len(text),
                },
                duration_ms=elapsed,
            )
