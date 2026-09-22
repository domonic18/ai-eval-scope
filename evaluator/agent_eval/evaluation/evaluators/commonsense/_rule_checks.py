"""InfoAccuracyEvaluator Phase 2 mixin — 可配置规则检查。

must_contain / must_not_contain / value_range / regex_match /
number_in_context / forbidden_pattern 六类规则的分派与逐条检查。
仅供 ``info_accuracy.InfoAccuracyEvaluator`` 组合，不独立使用。
"""

from __future__ import annotations

import re
from typing import Any


class InfoAccuracyRuleChecks:
    """知识准确性 Phase 2（可配置规则检查）——组合用 mixin。"""

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
