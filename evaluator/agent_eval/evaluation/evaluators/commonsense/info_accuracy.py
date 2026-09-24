"""commonsense.info_accuracy 评估器 — 多层检查架构的组合主体。

Phase 1 内置自动检查 / Phase 2 可配置规则检查 / Phase 2.5 Jev 误触预筛 /
Phase 3 LLM 语义验证分别定义在同包 `_builtin_checks` / `_rule_checks` /
`_jev_precheck` / `_llm_verify` mixin，本模块组合各层并承载编排入口
evaluate() 与计分。
"""

from __future__ import annotations

import time
from typing import Any

from agent_eval.core.types import ConstraintTier, EvalMethod, EvalStatus
from agent_eval.evaluation.base import BaseEvaluator
from agent_eval.evaluation.evaluators.commonsense._builtin_checks import (
    InfoAccuracyBuiltinChecks,
)
from agent_eval.evaluation.evaluators.commonsense._jev_precheck import InfoAccuracyJevPrecheck
from agent_eval.evaluation.evaluators.commonsense._llm_verify import InfoAccuracyLLMVerify
from agent_eval.evaluation.evaluators.commonsense._rule_checks import InfoAccuracyRuleChecks
from agent_eval.evaluation.evaluators.commonsense._shared import (
    _collect_file_texts,
    _load_fact_db,
)
from agent_eval.evaluation.registry import registry
from agent_eval.evaluation.text_utils import get_output_dir as _get_output_dir


@registry.register("commonsense.info_accuracy")
class InfoAccuracyEvaluator(
    InfoAccuracyBuiltinChecks,
    InfoAccuracyRuleChecks,
    InfoAccuracyJevPrecheck,
    InfoAccuracyLLMVerify,
    BaseEvaluator,
):
    """知识准确性检查 — 多层检查架构。

    Phase 1: 内置自动检查（算术表达式验证、常数校验、常识错误检测）
    Phase 2: 可配置规则检查（must_contain / must_not_contain / value_range / 新规则类型）
    Phase 2.5: Jev 高置信误触预筛（可选，jev_enabled + jev 线路注入时启用）
    Phase 3: LLM 语义验证（当 judge_orchestrator 可用时）
    """

    evaluator_id = "commonsense.info_accuracy"
    name = "知识准确性检查"
    tier = ConstraintTier.HARD_SCORE
    # 算术等式正则校验（非知识库事实验证）→ MATH_VERIFY：不派生 KNOWLEDGE_BASE 能力
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
        # subjects 为空/None → 加载全部参考数据集（知识库）；指定则只加载对应学科
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
                "source_files": [
                    {"filename": fn}
                    for fn in sorted({f["file"] for f in findings if f.get("file")})
                ],
                "checks_total": checks_total,
                "errors": len(errors),
                "warnings": len(warnings),
            },
            duration_ms=elapsed,
        )
