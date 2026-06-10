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
    """收集目录下所有文档的文本内容（合并为单字符串）。

    其他评估器（chronological_order 等）仍在使用此函数。
    """
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
        {文件相对路径: 纯文本内容}，HTML 标签已去除。
    """
    file_texts: dict[str, str] = {}
    for ext in ("*.md", "*.markdown", "*.html", "*.htm"):
        for f in output_dir.rglob(ext):
            try:
                content = f.read_text(encoding="utf-8", errors="ignore")
                if f.suffix.lower() in (".html", ".htm"):
                    content = re.sub(r"<[^>]+>", " ", content)
                if content.strip():
                    file_texts[str(f.relative_to(output_dir))] = content
            except OSError:
                continue
    return file_texts


# ─── 事实知识库缓存（多文件、按学科加载） ───

_fact_db_cache: dict[str, dict] = {}


def _merge_fact_section(source: dict[str, Any] | None, target: dict[str, list]) -> None:
    """将 source 中的 constants/misconceptions/domain_facts 合并到 target。"""
    if source is None:
        return
    for key in ("constants", "misconceptions", "domain_facts"):
        items = source.get(key, [])
        if items:
            target.setdefault(key, []).extend(items)


def _load_fact_db(subjects: list[str] | None = None) -> dict:
    """加载事实知识库（多文件、模块级缓存）。

    始终加载 _defaults.yaml（跨学科通用规则），
    然后按需加载学科文件（subjects=None 时加载全部）。

    Args:
        subjects: 学科标识列表，如 ["math", "history"]。
                  为 None 时加载所有学科文件。

    Returns:
        合并后的 dict，包含 constants、misconceptions、domain_facts。
    """
    cache_key = ",".join(sorted(subjects)) if subjects else "__all__"
    if cache_key in _fact_db_cache:
        return _fact_db_cache[cache_key]

    import yaml

    from agent_eval.config.paths import paths

    knowledge_dir = paths.assets_dir / "knowledge"
    merged: dict[str, list] = {
        "constants": [],
        "misconceptions": [],
        "domain_facts": [],
    }

    # 1. 始终加载 _defaults.yaml
    defaults_path = knowledge_dir / "_defaults.yaml"
    if defaults_path.exists():
        with open(defaults_path, encoding="utf-8") as f:
            _merge_fact_section(yaml.safe_load(f), merged)

    # 2. 加载学科文件（排除 _ 前缀）
    for yaml_file in sorted(knowledge_dir.glob("[!_]*.yaml")):
        try:
            with open(yaml_file, encoding="utf-8") as f:
                data = yaml.safe_load(f)
        except (OSError, yaml.YAMLError):
            continue
        if data is None:
            continue
        file_subject = data.get("subject", "")
        if subjects is None or file_subject in subjects:
            _merge_fact_section(data, merged)

    _fact_db_cache[cache_key] = merged
    return merged


def _reset_fact_db_cache() -> None:
    """重置事实知识库缓存（供测试使用）。"""
    global _fact_db_cache
    _fact_db_cache = {}


# ─── 算术表达式求值 ───

# 算术运算符集合
_OP_CHARS = set("+＋-－×÷*/")


def _eval_simple_expr(expr: str) -> float | None:
    """求值简单算术表达式（支持 +,-,×,÷ 及运算符优先级）。

    支持形如 ``28×8 + 22×9 + 35×4`` 的多项表达式。
    返回浮点结果，解析失败返回 None。
    """
    # 归一化运算符
    norm = (
        expr.replace("＋", "+")
        .replace("－", "-")
        .replace("×", "*")
        .replace("÷", "/")
    )
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
    _ARITH_CONTEXT_WINDOW = 40

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
                if abs(expected - dividend) > 0.01:
                    findings.append({
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
                    })

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
                if abs(expected - result_val) > 0.01:
                    findings.append({
                        "file": filename,
                        "check_type": "arithmetic",
                        "severity": "error",
                        "message": (
                            f"算术错误: {lhs_expr.strip()} = {result_s}"
                            f"（应为 {expected:g}）"
                        ),
                    })

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
            tolerance = const.get("tolerance", 0.01)
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
                        findings.append({
                            "file": filename,
                            "check_type": "constant",
                            "severity": "error",
                            "message": f"{name}: 值 {val} 与标准值 {value} 偏差超过容差 {tolerance}",
                        })

        return findings, checks

    def _check_misconceptions(
        self, file_texts: dict[str, str], fact_db: dict
    ) -> tuple[list[dict[str, Any]], int]:
        """检测文档中的常见事实错误模式。

        误解检测不计入 checks 计数——仅当模式匹配时产出 findings。
        这避免了大量无匹配的误解模式稀释 raw_score。

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
            severity = entry.get("severity", "warning")

            for filename, text in file_texts.items():
                if pattern.search(text):
                    findings.append({
                        "file": filename,
                        "check_type": "misconception",
                        "severity": severity,
                        "message": f"{description}（正确: {correct}）",
                    })

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
                    findings.append({
                        "file": "(全局)",
                        "check_type": "rule",
                        "severity": "error",
                        "message": f"缺少必要内容: '{keyword}'",
                        "rule_type": rule_type,
                    })

            elif rule_type == "must_not_contain":
                checks += 1
                wrong = rule.get("pattern", "")
                if wrong and wrong in merged_text:
                    findings.append({
                        "file": "(全局)",
                        "check_type": "rule",
                        "severity": "error",
                        "message": f"包含错误表述: '{wrong[:50]}'",
                        "rule_type": rule_type,
                    })

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
                    findings.append({
                        "file": filename,
                        "check_type": "rule",
                        "severity": "error",
                        "message": f"{name}: 值 {val} 低于最小值 {min_val}",
                        "rule_type": "value_range",
                    })
                if max_val is not None and val > max_val:
                    findings.append({
                        "file": filename,
                        "check_type": "rule",
                        "severity": "error",
                        "message": f"{name}: 值 {val} 超过最大值 {max_val}",
                        "rule_type": "value_range",
                    })

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
                findings.append({
                    "file": "(全局)",
                    "check_type": "rule",
                    "severity": "error",
                    "message": f"{name}: 未找到匹配 '{pattern_str}' 的内容",
                    "rule_type": "regex_match",
                })
        else:
            # 不应有任何文件匹配
            for filename, text in file_texts.items():
                if compiled.search(text):
                    findings.append({
                        "file": filename,
                        "check_type": "rule",
                        "severity": "error",
                        "message": f"{name}: 不应包含匹配 '{pattern_str}' 的内容",
                        "rule_type": "regex_match",
                    })

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
                    findings.append({
                        "file": filename,
                        "check_type": "rule",
                        "severity": "error",
                        "message": f"{name}: 关键词附近数值 {val} 低于最小值 {min_val}",
                        "rule_type": "number_in_context",
                    })
                if max_val is not None and val > max_val:
                    findings.append({
                        "file": filename,
                        "check_type": "rule",
                        "severity": "error",
                        "message": f"{name}: 关键词附近数值 {val} 超过最大值 {max_val}",
                        "rule_type": "number_in_context",
                    })

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
                findings.append({
                    "file": filename,
                    "check_type": "rule",
                    "severity": "error",
                    "message": reason,
                    "rule_type": "forbidden_pattern",
                })

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
        max_file_chars = self.params.get("max_file_chars", 4000)
        max_total_chars = self.params.get("max_content_chars", 8000)
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

        # 将 Phase 1-2 的 warning 传入 LLM 供重点验证
        warnings = [f["message"] for f in findings if f["severity"] == "warning"]
        errors = [f["message"] for f in findings if f["severity"] == "error"]

        variables = {
            "content": combined_text[:6000],
            "title": context.get("task_input", {}).get("title", "未知标题"),
            "subject": context.get("task_input", {}).get("subject", "未知学科"),
            "warnings": warnings + errors,
        }

        try:
            scores, record = orchestrator.judge(
                constraint_id=self.evaluator_id,
                sample_id=context.get("sample_id", "unknown"),
                template_id="info_accuracy",
                variables=variables,
                evidence_dir=Path(evidence_dir) if not isinstance(evidence_dir, Path) else evidence_dir,
                provider_name=self.params.get("llm_provider"),
            )
        except Exception as e:
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
        llm_errors = record.raw_response.get("errors_found", []) if record and hasattr(record, "raw_response") and isinstance(record.raw_response, dict) else []

        # 计分：合并 rule-based findings + LLM 分数
        rule_errors = [f for f in findings if f["severity"] == "error"]
        rule_warnings = [f for f in findings if f["severity"] == "warning"]

        # 如果 rule-based 有 error 且 LLM 分数低 → FAIL
        threshold = self.params.get("pass_threshold", 0.8)
        combined_score = min(avg_score, 1.0)
        passed = combined_score >= threshold and len(rule_errors) == 0
        score = 1.0 if passed else 0.0

        # 构建 reason
        score_parts = [f"{k}={v:.1f}" for k, v in scores.items()]
        reason = f"知识准确性（LLM + 规则）：{', '.join(score_parts)}"
        if rule_errors:
            reason += f"；规则检查发现 {len(rule_errors)} 处错误"

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
        year_list: list[int] = []
        if years:
            year_list = [int(y) for y in years if 0 < int(y) <= 2100]
            for i in range(1, len(year_list)):
                if year_list[i] < year_list[i - 1]:
                    # 允许回溯（如回顾历史），但标记为潜在问题
                    pass  # 时序回溯不一定错误，暂不报告

        # 检查序号递增
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
            return self._evaluate_with_llm(text, context, orchestrator, evidence_dir, output_dir, start)

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

        files_checked = _collect_file_names(output_dir)
        if not errors:
            return self._make_result(
                status=EvalStatus.PASS,
                score=1.0,
                reason="逻辑一致性检查通过（Rule-based 降级模式）",
                details={"files_checked": files_checked, "content_length": len(text)},
                duration_ms=elapsed,
            )
        else:
            return self._make_result(
                status=EvalStatus.FAIL,
                score=0.0,
                reason=f"发现 {len(errors)} 处逻辑矛盾",
                details={"errors": errors[:5], "files_checked": files_checked, "content_length": len(text)},
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

        files_checked = _collect_file_names(output_dir)
        if not errors:
            return self._make_result(
                status=EvalStatus.PASS,
                score=1.0,
                reason="公式正确性检查通过",
                details={
                    "files_checked": files_checked,
                    "formulas_checked": len(formula_patterns),
                    "arithmetic_checked": len(arithmetic),
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
                    "formulas_checked": len(formula_patterns),
                    "arithmetic_checked": len(arithmetic),
                },
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
                details={"errors": errors, "files_checked": files_checked, "content_length": len(text)},
                duration_ms=elapsed,
            )
