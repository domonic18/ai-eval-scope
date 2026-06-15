"""视觉质量评估器（多模态 LLM Judge）。

- vision.quality: 视觉质量（VISION）— HTML/Markdown 文档渲染截图后送多模态 LLM 评分

与文本 LLM 评估器的差异：视觉评估在不可用（无 Provider/无渲染器/无可渲染文档）时
降级为默认通过（PASS/0.7），而非计入 FAIL；因此 evaluate() 独立实现而非复用基类流程。
渲染 + judge 的核心逻辑放在 _render_and_judge，便于单测。
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from agent_eval.core.types import ConstraintTier, EvalMethod, EvalStatus
from agent_eval.evaluation.evaluators.quality_evaluators import (
    BaseLLMJudgeEvaluator,
    _get_output_dir,
)
from agent_eval.evaluation.models import ConstraintResult
from agent_eval.evaluation.registry import registry
from agent_eval.evaluation.vision import png_to_data_uri

# 视觉不可用时的降级分数（与文本 LLM 降级一致）
_DEGRADE_SCORE = 0.7


def _collect_doc_files(output_dir: Path) -> list[Path]:
    """收集 output 目录下的 HTML/Markdown 文档。"""
    files: list[Path] = []
    for ext in ("*.html", "*.htm", "*.md", "*.markdown"):
        files.extend(sorted(output_dir.rglob(ext)))
    return files


def _degrade(reason: str, *, duration_ms: float = 0.0) -> ConstraintResult:
    """构造视觉降级结果（PASS / 0.7）。"""
    return ConstraintResult(
        constraint_id="vision.quality",
        name="视觉质量",
        tier=ConstraintTier.SOFT,
        status=EvalStatus.PASS,
        score=_DEGRADE_SCORE,
        reason=f"视觉质量（视觉降级：{reason}，默认 {_DEGRADE_SCORE}）",
        duration_ms=duration_ms,
    )


@registry.register("vision.quality")
class VisionQualityEvaluator(BaseLLMJudgeEvaluator):
    """视觉质量评估 — 将文档渲染为截图，送多模态 LLM 评审排版/配色/层级/可读性。

    依赖 context 中的：
    - judge_orchestrator + evidence_dir（与文本 LLM 评估器一致）
    - screenshot_renderer：ScreenshotRenderer 实例（缺失则降级）
    - params.llm_provider：指定视觉 Provider（如 kimi_vision）
    """

    evaluator_id = "vision.quality"
    name = "视觉质量"
    tier = ConstraintTier.SOFT
    method = EvalMethod.VISION
    template_id = "visual_quality"

    def evaluate(self, sample: Any, context: dict[str, Any]) -> ConstraintResult:
        """视觉评估入口 — 渲染截图 → 多模态 LLM 评分 → 归一化。"""
        start = time.monotonic()

        orchestrator = context.get("judge_orchestrator")
        evidence_dir = context.get("evidence_dir")
        renderer = context.get("screenshot_renderer")

        # 降级：LLM 或渲染器不可用
        if orchestrator is None or evidence_dir is None:
            return _degrade("LLM 不可用", duration_ms=(time.monotonic() - start) * 1000)
        if renderer is None:
            return _degrade("未配置视觉渲染器", duration_ms=(time.monotonic() - start) * 1000)

        # 渲染截图
        ev = Path(evidence_dir) if not isinstance(evidence_dir, Path) else evidence_dir
        ev.mkdir(parents=True, exist_ok=True)
        output_dir = _get_output_dir(sample)
        doc_files = (
            _collect_doc_files(Path(output_dir)) if output_dir and output_dir.exists() else []
        )
        if not doc_files:
            return _degrade(
                "无 HTML/Markdown 文档可渲染", duration_ms=(time.monotonic() - start) * 1000
            )

        try:
            screenshots = renderer.render(doc_files, out_dir=ev)
        except Exception as e:
            return _degrade(f"截图渲染失败: {e}", duration_ms=(time.monotonic() - start) * 1000)
        if not screenshots:
            return _degrade("截图渲染返回空", duration_ms=(time.monotonic() - start) * 1000)

        # 编码为 data URI
        images = [png_to_data_uri(p) for p in screenshots]

        # 调用 LLM Judge（视觉路径）
        task_input = context.get("task_input", {})
        variables = {
            "title": task_input.get("title", "未知标题"),
            "num_documents": len(screenshots),
        }
        try:
            scores, record = orchestrator.judge(
                constraint_id=self.evaluator_id,
                sample_id=context.get("sample_id", "unknown"),
                template_id=self.template_id,
                variables=variables,
                evidence_dir=ev,
                provider_name=self.params.get("llm_provider"),
                images=images,
            )
        except Exception as e:
            elapsed = (time.monotonic() - start) * 1000
            return self._make_result(
                status=EvalStatus.ERROR,
                score=0.0,
                reason=f"视觉 LLM Judge 调用失败: {e}",
                duration_ms=elapsed,
            )

        elapsed = (time.monotonic() - start) * 1000
        return self._build_vision_result(scores, record, screenshots, ev, elapsed)

    def _build_vision_result(
        self,
        scores: dict[str, Any],
        record: Any,
        screenshots: list[Path],
        evidence_dir: Path,
        elapsed: float,
    ) -> ConstraintResult:
        """将 LLM 评分归一化并构造 ConstraintResult。"""
        # 直接按已知 visual_quality 维度加权（与基类归一化逻辑一致，
        # record 不持有模板引用，无需经过 orchestrator 取模板）
        dims = _VISUAL_DIMS  # (dim_id, name, weight)
        total_weight = sum(w for _, _, w in dims)
        weighted = sum(scores.get(did, 0.0) * w for did, _, w in dims)
        normalized = (weighted / total_weight / 10.0) if total_weight > 0 else 0.0
        normalized = max(0.0, min(1.0, normalized))

        score_parts = [f"{name}: {scores.get(did, 0.0):.1f}" for did, name, _ in dims]
        reason = f"{self.name}（视觉 LLM 评估）：{', '.join(score_parts)}"
        if record and getattr(record, "summary", ""):
            reason += f" — {record.summary[:150]}"

        details: dict[str, Any] = {
            "scores": scores,
            "confidence": record.confidence if record else {},
            "screenshot_paths": [f"evidence/{p.name}" for p in screenshots],
            "dimensions": [
                {
                    "id": did,
                    "name": name,
                    "score": scores.get(did, 0.0),
                    "weight": w,
                    "confidence": (record.confidence.get(did, "unknown") if record else "unknown"),
                }
                for did, name, w in dims
            ],
        }
        if record and getattr(record, "summary", ""):
            details["summary"] = record.summary

        record_path = f"evidence/{record.judge_id}.json" if record else None

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


# 视觉模板维度定义（与 assets/prompts/visual_quality.yaml 对齐）
_VISUAL_DIMS: list[tuple[str, str, float]] = [
    ("layout", "排版", 0.3),
    ("color_scheme", "配色", 0.25),
    ("information_hierarchy", "信息层级", 0.25),
    ("readability", "可读性", 0.2),
]
