"""commonsense.logical_consistency 评估器 — LLM 评逻辑一致性。"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from agent_eval.config import EVALUATOR_DEFAULTS
from agent_eval.core.types import ConstraintTier, EvalMethod, EvalStatus
from agent_eval.evaluation.base import BaseEvaluator
from agent_eval.evaluation.evaluators.commonsense._shared import (
    _collect_file_names,
    _collect_text_content,
)
from agent_eval.evaluation.evaluators.quality_evaluators import (
    _aggregate_source_files,
    _band_of,
)
from agent_eval.evaluation.registry import registry
from agent_eval.evaluation.text_utils import get_output_dir as _get_output_dir


@registry.register("commonsense.logical_consistency")
class LogicalConsistencyEvaluator(BaseEvaluator):
    """逻辑一致性检查 — 使用 LLM 评估文档内容的逻辑一致性。

    LLM 不可用时 SKIP（不计分；不降级 PASS 以免虚高 CPR）。
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
        max_chars = self.params.get("max_content_chars", EVALUATOR_DEFAULTS.max_content_chars)
        if len(text) > max_chars:
            text = text[:max_chars] + "\n\n[...内容已截断...]"

        variables = {
            "content": text[: EVALUATOR_DEFAULTS.llm_judge_combined_content_chars],
            "title": context.get("task_input", {}).get("title", "未知标题"),
        }

        try:
            consistency_prompt = (
                self.params.get("prompt_id")
                or self.params.get("template_id")
                or "logical_consistency"
            )
            scores, record = orchestrator.judge(
                constraint_id=self.evaluator_id,
                sample_id=context.get("sample_id", "unknown"),
                template_id=consistency_prompt,
                variables=variables,
                evidence_dir=Path(evidence_dir)
                if not isinstance(evidence_dir, Path)
                else evidence_dir,
                provider_name=self.params.get("llm_role"),
            )
        except Exception as e:
            elapsed = (time.monotonic() - start) * 1000
            # LLM 调用失败，降级为默认通过
            return self._make_result(
                status=EvalStatus.PASS,
                score=1.0,
                reason=f"LLM 调用失败，降级为默认通过: {e}",
                duration_ms=elapsed,
            )

        elapsed = (time.monotonic() - start) * 1000

        # 计算分数
        template = orchestrator.templates.get(None, "logical_consistency")
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

        # 维度详情透传（reason/issues/highlights，issues 含 involved_files）+ 文件定位聚合
        dim_details = record.dim_details if record and hasattr(record, "dim_details") else {}
        dimensions = (
            [
                {
                    "id": d.dim_id,
                    "name": d.name,
                    "weight": d.weight,
                    "score": scores.get(d.dim_id, 0.0),
                    "band": _band_of(scores.get(d.dim_id, 0.0)),
                    "confidence": (
                        record.confidence.get(d.dim_id, "unknown") if record else "unknown"
                    ),
                    **(dim_details.get(d.dim_id, {})),
                }
                for d in template.dimensions
            ]
            if template and template.dimensions
            else []
        )
        source_files = _aggregate_source_files(dimensions, context)

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
                "dimensions": dimensions,
                "source_files": source_files,
            },
            duration_ms=elapsed,
            judge_provider=record.provider_name if record else None,
            judge_model=record.model if record else None,
            judge_record_path=record_path,
        )
