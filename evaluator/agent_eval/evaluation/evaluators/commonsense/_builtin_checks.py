"""InfoAccuracyEvaluator Phase 1 mixin — 内置自动检查。

算术等式验证（多项式 + 带余数除法）、科学/数学常数校验、常识错误模式检测。
仅供 ``info_accuracy.InfoAccuracyEvaluator`` 组合，不独立使用。
"""

from __future__ import annotations

import re
from typing import Any

from agent_eval.config import EVALUATOR_DEFAULTS
from agent_eval.evaluation.evaluators.commonsense._shared import (
    _VERTICAL_CALC_KEYWORDS,
    _eval_simple_expr,
)


class InfoAccuracyBuiltinChecks:
    """知识准确性 Phase 1（内置自动检查）——组合用 mixin。"""

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

                expected_val = _eval_simple_expr(lhs_expr)
                if expected_val is None:
                    continue

                checks += 1
                if abs(expected_val - result_val) > EVALUATOR_DEFAULTS.arith_tolerance:
                    findings.append(
                        {
                            "file": filename,
                            "check_type": "arithmetic",
                            "severity": "error",
                            "message": (
                                f"算术错误: {lhs_expr.strip()} = {result_s}（应为 {expected_val:g}）"
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
