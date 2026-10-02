"""InfoAccuracyEvaluator Phase 3 mixin — LLM 语义验证。

LLM 事实性评估（与规则 findings 解耦）+ fact_verdict 规则误报二次确认。
仅供 ``info_accuracy.InfoAccuracyEvaluator`` 组合，不独立使用。
"""

from __future__ import annotations

import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from agent_eval.config import EVALUATOR_DEFAULTS
from agent_eval.core.types import EvalStatus
from agent_eval.evaluation.evaluators.commonsense._shared import (
    FACT_VERDICT_BATCH_SIZE,
    logger,
)


class InfoAccuracyLLMVerify:
    """知识准确性 Phase 3（LLM 语义验证）——组合用 mixin。

    依赖组合主体（InfoAccuracyEvaluator / BaseEvaluator）提供的成员：
    evaluator_id / name / tier / params / _compute_result。
    """

    # 组合主体成员声明（仅注解，零运行时）——供类型检查器解析 self.* 引用
    evaluator_id: str
    name: str
    tier: Any
    params: dict[str, Any]
    _compute_result: Callable[..., Any]
    _apply_decision_filter: Callable[..., Any]

    def _effective_prompt_id(self, default: str) -> str:
        """优先使用规则层传入的 prompt_id，回退到 params.template_id，最后才是默认值。"""
        return self.params.get("prompt_id") or self.params.get("template_id") or default

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
        # 对照实验证实，把规则误报（如"水的pH 800"实为报告字数）
        # 作为"可疑条目"传给 LLM 会严重污染整体评分（化学样本 factual 4.0→10.0）。
        # 规则 findings 由 fact_verdict 过滤后经 rule_errors 独立计分，与 LLM 解耦。
        variables = {
            "content": combined_text[: EVALUATOR_DEFAULTS.llm_judge_combined_content_chars],
            "title": context.get("task_input", {}).get("title", "未知标题"),
            "subject": context.get("task_input", {}).get("subject", "未知学科"),
        }

        try:
            info_prompt = self._effective_prompt_id("info_accuracy")
            scores, record = orchestrator.judge(
                constraint_id=self.evaluator_id,
                sample_id=context.get("sample_id", "unknown"),
                template_id=info_prompt,
                variables=variables,
                evidence_dir=Path(evidence_dir)
                if not isinstance(evidence_dir, Path)
                else evidence_dir,
                provider_name=self.params.get("llm_role"),
            )
        except Exception:
            # LLM 调用失败，回退到 Phase 1-2 的结果
            return self._compute_result(file_texts, findings, start, checks_total=0)

        elapsed = (time.monotonic() - start) * 1000

        # 计算加权分数
        template = orchestrator.templates.get(None, self._effective_prompt_id("info_accuracy"))
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

        # 构建 reason（面向用户可读：分数型失败透出维度评分与通过线，规则型失败列出具体错误）
        if passed:
            reason = "知识准确性（LLM + 规则）：通过"
        else:
            reason = "知识准确性（LLM + 规则）：未通过"
            # 分数型失败（无规则错误、纯 LLM 评分不达标）必须给出可解释信息，
            # 否则用户只见「未通过」三个字无从定位（对齐兄弟评估器透出维度分的惯例）。
            # 分数过线但被规则错误致败时不拼分数条款——「加权 8.6 低于通过线 8.0」
            # 属自相矛盾文案，失败归因已由下方「发现错误」条款承载（run 20260913_050312）
            if scores and combined_score < threshold:
                dim_names = (
                    {d.dim_id: d.name for d in template.dimensions}
                    if template and template.dimensions
                    else {}
                )
                dim_desc = "、".join(
                    f"{dim_names.get(k, k)} {float(v):g}" for k, v in scores.items()
                )
                reason += (
                    f"；LLM 评分：{dim_desc}"
                    f"（加权 {combined_score * 10:.1f}/10，低于通过线 {threshold * 10:.1f}）"
                )
        if rule_errors:
            # 列出 LLM 二次确认的具体错误（_llm_reason 优先，回退规则描述），最多 5 条
            err_descs = [
                (f.get("_llm_reason") or f.get("message") or f.get("reason") or "未提供详情")
                for f in rule_errors[:5]
            ]
            detail = "；".join(d.strip() for d in err_descs if d and d.strip())
            suffix = f"（共 {len(rule_errors)} 处）" if len(rule_errors) > 5 else ""
            reason += f"；发现错误（经 LLM 二次确认）：{detail}{suffix}"
        elif error_findings:
            # 救援路径要如实区分：判定专线预筛剔除（未送 LLM 复核）与 fact_verdict
            # 二次确认不成立是不同机制，混称会误导审计（对照实验中 ON 版 reason
            # 曾在零 LLM 复核时谎称「经 LLM 二次确认」）
            dropped = sum(1 for f in error_findings if f.get("_decision_filtered"))
            total = len(error_findings)
            if dropped == total:
                reason += f"；规则标记 {total} 处疑似错误经判定专线预筛剔除（未送 LLM 复核）"
            elif dropped:
                reason += (
                    f"；规则标记 {total} 处疑似错误均不成立"
                    f"（判定专线剔除 {dropped} 处，其余 {total - dropped} 处经 LLM 二次确认不成立）"
                )
            else:
                reason += f"；规则标记 {total} 处疑似错误经 LLM 二次确认均不成立"

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
                "source_files": [
                    {"filename": fn}
                    for fn in sorted({f["file"] for f in findings if f.get("file")})
                ],
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

        候选构建前先经判定专线高置信误触预筛（_apply_decision_filter，未启用时原样直构）：
        被剔除候选写 _decision_filtered 审计字段并从复核集合排除——判定专线只有剔除权，
        升级侧候选的裁定语义与本函数原先行为完全一致。
        """
        candidates = self._apply_decision_filter(error_findings, file_texts, context, evidence_dir)
        ev_dir = evidence_dir if isinstance(evidence_dir, Path) else Path(evidence_dir)
        batch_size = self.params.get("fact_verdict_batch_size", FACT_VERDICT_BATCH_SIZE)
        max_concurrency = self.params.get(
            "fact_verdict_max_concurrency", EVALUATOR_DEFAULTS.fact_verdict_max_concurrency
        )
        variables_base = {
            "title": context.get("task_input", {}).get("title", "未知标题"),
            "subject": context.get("task_input", {}).get("subject", "未知学科"),
        }

        # 分批调用 fact_verdict（候选过多时单次 prompt 过大会导致 LLM 调用失败）
        verdict_prompt_id = self.params.get("fact_verdict_prompt_id", "fact_verdict")
        batches: list[list[dict[str, Any]]] = [
            candidates[bs : bs + batch_size] for bs in range(0, len(candidates), batch_size)
        ]

        def _judge_batch(batch_idx: int) -> list[dict[str, Any]]:
            _scores, record = orchestrator.judge(
                constraint_id=self.evaluator_id,
                sample_id=context.get("sample_id", "unknown"),
                template_id=verdict_prompt_id,
                variables={**variables_base, "candidates": batches[batch_idx]},
                evidence_dir=ev_dir,
                provider_name=self.params.get("llm_role"),
                judge_id_suffix=f"fact_verdict_{batch_idx}",
            )
            parsed = getattr(record, "parsed_scores", None) if record else None
            return parsed.get("verdicts", []) if isinstance(parsed, dict) else []

        def _keep_batch(batch_idx: int, exc: bool) -> None:
            logger.warning(
                "fact_verdict 批次裁定失败，该批保留（召回优先）",
                batch=batch_idx,
                batch_size=len(batches[batch_idx]),
                exc_info=exc,
            )

        # 批间无顺序依赖（verdicts 按自带 index 键控合并），按结果槽位回填；
        # 单批失败 → 该批空裁定 → findings 缺裁定 → 默认保留（召回优先，不漏报）
        verdicts_by_batch: list[list[dict[str, Any]]] = [[] for _ in batches]
        if len(batches) > 1 and max_concurrency > 1:
            executor = ThreadPoolExecutor(max_workers=min(max_concurrency, len(batches)))
            try:
                futures = [executor.submit(_judge_batch, i) for i in range(len(batches))]
                for i, future in enumerate(futures):
                    try:
                        verdicts_by_batch[i] = future.result()
                    except Exception:
                        _keep_batch(i, True)
            finally:
                executor.shutdown(wait=False, cancel_futures=True)
        else:
            for i in range(len(batches)):
                try:
                    verdicts_by_batch[i] = _judge_batch(i)
                except Exception:
                    _keep_batch(i, True)
        all_verdicts: list[dict[str, Any]] = [
            v for batch_verdicts in verdicts_by_batch for v in batch_verdicts
        ]

        verdict_map = {
            v.get("index"): v for v in all_verdicts if isinstance(v, dict) and "index" in v
        }

        confirmed: list[dict[str, Any]] = []
        for i, f in enumerate(error_findings):
            if f.get("_decision_filtered"):
                continue  # 判定专线高置信误触已剔除：不进 rule_errors（filter-only 剔除权）
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
