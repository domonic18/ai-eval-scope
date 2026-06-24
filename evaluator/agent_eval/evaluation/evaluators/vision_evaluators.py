"""视觉质量评估器（多模态 LLM Judge）。

- vision.quality: 视觉质量（VISION）— 对每个 HTML/Markdown 文档渲染截图后，逐文档
  送多模态 LLM 评分，再按维度取均值聚合为约束分。

与文本 LLM 评估器的差异：视觉评估在不可用（无 Provider/无渲染器/无可渲染文档）时
降级为默认通过（PASS/0.7），而非计入 FAIL；因此 evaluate() 独立实现而非复用基类流程。

逐文档评估：每个文档独立渲染 + 独立 judge 调用（images=[单图]），通过
judge_id_suffix 保证 evidence 文件名唯一。逐文档分数按维度取均值，使最终分数反映
整本文档集的视觉质量，而非单个抽样页。
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from agent_eval.config import EVALUATOR_DEFAULTS
from agent_eval.core.types import ConstraintTier, EvalMethod, EvalStatus
from agent_eval.evaluation.evaluators.quality_evaluators import (
    BaseLLMJudgeEvaluator,
    _get_output_dir,
)
from agent_eval.evaluation.models import ConstraintResult
from agent_eval.evaluation.registry import registry
from agent_eval.evaluation.vision import png_to_data_uri


def _collect_doc_files(output_dir: Path) -> list[Path]:
    """收集 output 目录下的 HTML/Markdown 文档（按路径排序，确定性）。"""
    files: list[Path] = []
    for ext in ("*.html", "*.htm", "*.md", "*.markdown"):
        files.extend(sorted(output_dir.rglob(ext)))
    return files


def _degrade(reason: str, *, duration_ms: float = 0.0) -> ConstraintResult:
    """构造视觉降级结果（SKIP，不计入得分）。"""
    return ConstraintResult(
        constraint_id="vision.quality",
        name="视觉质量",
        tier=ConstraintTier.SOFT,
        status=EvalStatus.SKIP,
        score=0.0,
        reason=f"视觉质量（视觉跳过：{reason}，不计入得分）",
        duration_ms=duration_ms,
    )


@registry.register("vision.quality")
class VisionQualityEvaluator(BaseLLMJudgeEvaluator):
    """视觉质量评估 — 逐文档渲染截图 → 多模态 LLM 评分 → 按维度均值聚合。

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
        """视觉评估入口 — 逐文档渲染截图 → 逐文档多模态评分 → 均值聚合。"""
        start = time.monotonic()

        orchestrator = context.get("judge_orchestrator")
        evidence_dir = context.get("evidence_dir")
        renderer = context.get("screenshot_renderer")

        # 降级：LLM 或渲染器不可用
        if orchestrator is None or evidence_dir is None:
            return _degrade("LLM 不可用", duration_ms=(time.monotonic() - start) * 1000)
        if renderer is None:
            return _degrade("未配置视觉渲染器", duration_ms=(time.monotonic() - start) * 1000)

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

        # 渲染全部文档截图（一次性批量渲染，复用浏览器进程）
        try:
            screenshots = renderer.render(doc_files, out_dir=ev)
        except Exception as e:
            return _degrade(f"截图渲染失败: {e}", duration_ms=(time.monotonic() - start) * 1000)
        if not screenshots:
            return _degrade("截图渲染返回空", duration_ms=(time.monotonic() - start) * 1000)

        # 逐文档视觉打分
        task_input = context.get("task_input", {})
        provider_name = self.params.get("llm_provider")
        per_doc = self._judge_each(
            orchestrator,
            screenshots=screenshots,
            doc_files=doc_files,
            sample_id=context.get("sample_id", "unknown"),
            evidence_dir=ev,
            title=task_input.get("title", "未知标题"),
            provider_name=provider_name,
            trace_id=context.get("trace_id"),
        )

        elapsed = (time.monotonic() - start) * 1000

        # 全部文档打分失败 → 降级（避免均值无意义）
        if not per_doc:
            return _degrade("全部文档视觉评估失败", duration_ms=elapsed)

        return self._build_vision_result(per_doc, screenshots, len(doc_files), elapsed)

    def _judge_each(
        self,
        orchestrator: Any,
        *,
        screenshots: list[Path],
        doc_files: list[Path],
        sample_id: str,
        evidence_dir: Path,
        title: str,
        provider_name: str | None,
        trace_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """逐文档调用视觉 judge，返回每文档评估记录列表。

        每条记录：{doc_name, scores, summary, judge_id, ok}。单文档失败（异常）记
        ok=False 并继续，不中断其余文档。
        """
        records: list[dict[str, Any]] = []
        for idx, (doc, png) in enumerate(zip(doc_files, screenshots, strict=False)):
            doc_name = Path(doc).stem
            variables = {"title": title, "num_documents": 1}
            try:
                scores, record = orchestrator.judge(
                    constraint_id=self.evaluator_id,
                    sample_id=sample_id,
                    template_id=self.template_id,
                    variables=variables,
                    evidence_dir=evidence_dir,
                    provider_name=provider_name,
                    images=[png_to_data_uri(png)],
                    judge_id_suffix=f"doc{idx:03d}_{doc_name}",
                    trace_id=trace_id,
                )
                records.append(
                    {
                        "doc_name": doc_name,
                        "screenshot": png.name,
                        "scores": scores,
                        "summary": getattr(record, "summary", "") if record else "",
                        "judge_id": getattr(record, "judge_id", "") if record else "",
                        "model": getattr(record, "model", "") if record else "",
                        "confidence": getattr(record, "confidence", {}) if record else {},
                        "ok": True,
                    }
                )
            except Exception as e:  # noqa: BLE001 — 单文档失败不致命
                records.append(
                    {"doc_name": doc_name, "screenshot": png.name, "error": str(e), "ok": False}
                )
        return records

    def _build_vision_result(
        self,
        per_doc: list[dict[str, Any]],
        screenshots: list[Path],
        total_docs: int,
        elapsed: float,
    ) -> ConstraintResult:
        """将逐文档分数按维度取均值，归一化并构造 ConstraintResult。"""
        ok_docs = [d for d in per_doc if d.get("ok")]
        dims = EVALUATOR_DEFAULTS.vision_quality_dimensions  # (dim_id, name, weight)
        # 逐文档均值聚合的置信度：覆盖率高（无失败文档）=high，否则 low
        dim_confidence = "high" if len(ok_docs) == total_docs and total_docs > 0 else "low"

        # 按维度取所有成功文档的均值
        avg_scores: dict[str, float] = {}
        for did, _, _ in dims:
            vals = [float(d["scores"].get(did, 0.0)) for d in ok_docs if "scores" in d]
            avg_scores[did] = sum(vals) / len(vals) if vals else 0.0

        # 加权归一化
        total_weight = sum(w for _, _, w in dims)
        weighted = sum(avg_scores.get(did, 0.0) * w for did, _, w in dims)
        normalized = (weighted / total_weight / 10.0) if total_weight > 0 else 0.0
        normalized = max(0.0, min(1.0, normalized))

        score_parts = [f"{name}: {avg_scores.get(did, 0.0):.1f}" for did, name, _ in dims]
        reason = (
            f"{self.name}（视觉 LLM 逐文档评估，均值）：{', '.join(score_parts)}"
            f" [评估 {len(ok_docs)}/{total_docs} 文档]"
        )
        # 取第一条非空 summary 作为代表
        rep_summary = next((d.get("summary", "") for d in ok_docs if d.get("summary")), "")
        if rep_summary:
            reason += f" — {rep_summary[:120]}"

        details: dict[str, Any] = {
            "scores": avg_scores,
            "screenshot_paths": [str(p) for p in screenshots],
            "total_documents": total_docs,
            "evaluated_documents": len(ok_docs),
            "per_document": [
                {
                    "doc": d.get("doc_name"),
                    "screenshot": d.get("screenshot"),
                    "scores": d.get("scores"),
                    **({"error": d["error"]} if not d.get("ok") and "error" in d else {}),
                    "judge_record": (
                        f"evidence/{d['judge_id']}.json"
                        if d.get("ok") and d.get("judge_id")
                        else None
                    ),
                }
                for d in per_doc
            ],
            "dimensions": [
                {
                    "id": did,
                    "name": name,
                    "score": avg_scores.get(did, 0.0),
                    "weight": w,
                    # 逐文档均值聚合：置信度反映文档覆盖度（全部成功=high）
                    "confidence": dim_confidence,
                }
                for did, name, w in dims
            ],
        }
        if rep_summary:
            details["summary"] = rep_summary

        # judge_record_path：取第一个成功文档的（详情中 per_document 有全部）
        first_ok = ok_docs[0] if ok_docs else None
        record_path = (
            f"evidence/{first_ok['judge_id']}.json"
            if first_ok and first_ok.get("judge_id")
            else None
        )
        # provider/model 取自评估器配置与首成功文档（逐文档共用同一 provider）
        provider_name = self.params.get("llm_provider")
        model_name = first_ok.get("model", "") if first_ok else ""

        return ConstraintResult(
            constraint_id=self.evaluator_id,
            name=self.name,
            tier=self.tier,
            status=EvalStatus.PASS
            if normalized >= EVALUATOR_DEFAULTS.llm_judge_pass_threshold
            else EvalStatus.FAIL,
            score=normalized,
            reason=reason,
            details=details,
            duration_ms=elapsed,
            judge_provider=provider_name,
            judge_model=model_name or None,
            judge_record_path=record_path,
        )
