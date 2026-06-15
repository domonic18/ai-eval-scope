"""软约束与偏好约束评估器（5 项）。

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
from agent_eval.evaluation.evaluators.commonsense_evaluators import _get_output_dir
from agent_eval.evaluation.models import ConstraintResult
from agent_eval.evaluation.registry import registry
from agent_eval.evaluation.text_utils import collect_text_content

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
            text = collect_text_content(output_dir)

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

        # 调用 JudgeOrchestrator（通过钩子，视觉等子类可覆盖以传 images）
        try:
            scores, record, extra_details = self._invoke_judge(
                orchestrator,
                sample=sample,
                text=text,
                context=context,
                evidence_dir=evidence_dir,
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
            weighted_score = sum(scores.get(d.dim_id, 0.0) * d.weight for d in template.dimensions)
            normalized = (weighted_score / total_weight / 10.0) if total_weight > 0 else 0.0
        else:
            # 无维度信息，取平均
            vals = list(scores.values())
            normalized = (sum(vals) / len(vals) / 10.0) if vals else 0.0

        normalized = max(0.0, min(1.0, normalized))

        # 构建评估原因 — 使用维度中文名
        score_parts = []
        if template and template.dimensions:
            for dim in template.dimensions:
                dim_score = scores.get(dim.dim_id, 0.0)
                score_parts.append(f"{dim.name}: {dim_score:.1f}")
        else:
            score_parts = [f"{k}: {v:.1f}" for k, v in scores.items()]

        reason = f"{self.name}（LLM 评估）：{', '.join(score_parts)}"
        if record and hasattr(record, "summary") and record.summary:
            reason += f" — {record.summary[:150]}"

        # 构建 details — 包含结构化维度详情和 LLM 总结
        details: dict[str, Any] = {
            "scores": scores,
            "confidence": record.confidence if record else {},
        }
        # 合并子类附加的详情（如视觉截图路径）
        if extra_details:
            details.update(extra_details)
        if record and hasattr(record, "summary"):
            details["summary"] = record.summary
        if template and template.dimensions:
            details["dimensions"] = [
                {
                    "id": dim.dim_id,
                    "name": dim.name,
                    "score": scores.get(dim.dim_id, 0.0),
                    "weight": dim.weight,
                    "confidence": (
                        record.confidence.get(dim.dim_id, "unknown") if record else "unknown"
                    ),
                }
                for dim in template.dimensions
            ]

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
            details=details,
            duration_ms=elapsed,
            judge_provider=record.provider_name if record else None,
            judge_model=record.model if record else None,
            judge_record_path=record_path,
        )

    def _invoke_judge(
        self,
        orchestrator: Any,
        *,
        sample: Any,
        text: str,
        context: dict[str, Any],
        evidence_dir: Any,
        provider_name: str | None,
    ) -> tuple[dict[str, Any], Any, dict[str, Any]]:
        """调用 JudgeOrchestrator 执行评估（钩子）。

        默认实现：构建模板变量后调用 orchestrator.judge()。
        子类（如视觉评估器）可覆盖以传入 images 等额外参数。

        Returns:
            (scores, JudgeRecord, extra_details) 三元组。
            extra_details 为附加到 ConstraintResult.details 的字段（可空 dict）。
        """
        variables = self._build_variables(text, context)
        ev = Path(evidence_dir) if not isinstance(evidence_dir, Path) else evidence_dir
        scores, record = orchestrator.judge(
            constraint_id=self.evaluator_id,
            sample_id=context.get("sample_id", "unknown"),
            template_id=self.template_id,
            variables=variables,
            evidence_dir=ev,
            provider_name=provider_name,
        )
        return scores, record, {}

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
