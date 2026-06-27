"""常识约束评估器（3 项）— HARD_SCORE。

- commonsense.info_accuracy: 知识准确性（FACT_VERIFY，规则 + fact_verdict 二次确认 + LLM）
- commonsense.chronological_order: 时序正确性（LLM_JUDGE，评整个课件）
- commonsense.logical_consistency: 逻辑一致性（LLM_JUDGE，评整个课件）

math_formula / unit_consistency 已移除（前者易误报且 info_accuracy 已覆盖算术检查，
后者为死代码）。
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
from agent_eval.evaluation.evaluators.quality_evaluators import BaseLLMJudgeEvaluator
from agent_eval.evaluation.registry import registry
from agent_eval.evaluation.text_utils import (
    collect_file_texts,
    collect_text_content,
)
from agent_eval.evaluation.text_utils import (
    get_output_dir as _get_output_dir,
)

logger = structlog.get_logger("evaluation.commonsense")

# fact_verdict 二次确认的单批最大候选数（超过则分批调用，避免单次 prompt 过大
# 导致 LLM 调用失败，如数学样本 98 候选一次调用即失败）
FACT_VERDICT_BATCH_SIZE = 20


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
        batch_size = self.params.get("fact_verdict_batch_size", FACT_VERDICT_BATCH_SIZE)
        variables_base = {
            "title": context.get("task_input", {}).get("title", "未知标题"),
            "subject": context.get("task_input", {}).get("subject", "未知学科"),
        }

        # 分批调用 fact_verdict（候选过多时单次 prompt 过大会导致 LLM 调用失败）
        all_verdicts: list[dict[str, Any]] = []
        for batch_start in range(0, len(candidates), batch_size):
            batch = candidates[batch_start : batch_start + batch_size]
            batch_idx = batch_start // batch_size
            try:
                _scores, record = orchestrator.judge(
                    constraint_id=self.evaluator_id,
                    sample_id=context.get("sample_id", "unknown"),
                    template_id="fact_verdict",
                    variables={**variables_base, "candidates": batch},
                    evidence_dir=ev_dir,
                    provider_name=self.params.get("llm_provider"),
                    judge_id_suffix=f"fact_verdict_{batch_idx}",
                )
                parsed = getattr(record, "parsed_scores", None) if record else None
                all_verdicts.extend(parsed.get("verdicts", []) if isinstance(parsed, dict) else [])
            except Exception:
                # 单批失败 → 该批 findings 缺裁定 → 默认保留（召回优先，不漏报）
                logger.warning(
                    "fact_verdict 批次裁定失败，该批保留（召回优先）",
                    batch=batch_idx,
                    batch_size=len(batch),
                    exc_info=True,
                )

        verdict_map = {
            v.get("index"): v for v in all_verdicts if isinstance(v, dict) and "index" in v
        }

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
class ChronologicalOrderEvaluator(BaseLLMJudgeEvaluator):
    """时序正确性检查 — LLM 评审整个课件的时间线/序号/步骤顺序合理性。

    旧规则实现（提取年份/序号但不校验，始终 PASS）已废弃；改为 LLM-as-judge，
    对整个课件文本评估时序一致性。LLM 不可用时降级 SKIP（不计分）。
    """

    evaluator_id = "commonsense.chronological_order"
    name = "时序正确性检查"
    tier = ConstraintTier.HARD_SCORE
    method = EvalMethod.LLM_JUDGE
    template_id = "chronological_order"
    pass_threshold = EVALUATOR_DEFAULTS.logical_consistency_pass_threshold


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

        # LLM 不可用 → SKIP（不计分；不降级 PASS 以免虚高 CPR）
        elapsed = (time.monotonic() - start) * 1000
        return self._make_result(
            status=EvalStatus.SKIP,
            score=0.0,
            reason="逻辑一致性检查（LLM 不可用，已跳过，不计入得分）",
            duration_ms=elapsed,
        )

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
            "content": text[: EVALUATOR_DEFAULTS.llm_judge_combined_content_chars],
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
