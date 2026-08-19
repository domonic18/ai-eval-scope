"""内容完整性评估器 — HARD_GATE。

- format.content_completeness: 空壳/占位文件检测（规则初筛 + LLM 语义二次确认）

设计动机：课件包中某结构位置生成失败时，产出方常留下一个格式合法但无教学内容的
空壳页。此类文件在「找错式」门控（格式/知识/逻辑）下全部无辜通过，导致交付不
完整的包仍获得高分。本评估器回答「该交付的内容在不在」：

1. 规则初筛（包内自适应，无绝对字数阈值）：剥标签正文低于包内中位数的
   ``empty_body_ratio`` 倍（且无实质媒体元素）→ 疑似空壳。相对比例跨学段/
   学科/页面类型自适应，避免「练习页/封面页天然短」的误报与漏报。
2. LLM 二次确认（可选，复用 info_accuracy→fact_verdict 范式）：疑似文件批量
   语义裁定，剔除合法短页误报；LLM 不可用时保留规则判定（召回优先）。
"""

from __future__ import annotations

import re
import statistics
import time
from pathlib import Path
from typing import Any

import structlog

from agent_eval.config import EVALUATOR_DEFAULTS
from agent_eval.core.types import ConstraintTier, EvalMethod, EvalStatus
from agent_eval.evaluation.base import BaseEvaluator
from agent_eval.evaluation.registry import registry
from agent_eval.evaluation.text_utils import file_to_text
from agent_eval.evaluation.text_utils import (
    get_output_dir as _get_output_dir,
)

logger = structlog.get_logger("evaluation.content_completeness")

_CONTENT_EXTENSIONS = {".html", ".htm", ".md", ".markdown"}


@registry.register("format.content_completeness")
class ContentCompletenessEvaluator(BaseEvaluator):
    """内容完整性检查 — 内容文件不得为空壳/占位。"""

    evaluator_id = "format.content_completeness"
    name = "内容完整性检查"
    tier = ConstraintTier.HARD_GATE
    method = EvalMethod.RULE

    def evaluate(self, sample: Any, context: dict[str, Any]) -> Any:
        start = time.monotonic()

        output_dir = _get_output_dir(sample)
        if output_dir is None or not output_dir.exists():
            return self._make_result(
                status=EvalStatus.FAIL,
                score=0.0,
                reason="输出目录不存在",
                duration_ms=self._elapsed_ms(start),
            )

        files = sorted(
            f
            for f in output_dir.rglob("*")
            if f.is_file()
            and f.name != "_manifest.json"
            and f.suffix.lower() in _CONTENT_EXTENSIONS
        )
        if not files:
            return self._make_result(
                status=EvalStatus.FAIL,
                score=0.0,
                reason="无内容文件（md/html）",
                duration_ms=self._elapsed_ms(start),
            )

        ratio = float(
            self.params.get("empty_body_ratio", EVALUATOR_DEFAULTS.content_empty_body_ratio)
        )
        media_tags = self.params.get("media_tags") or EVALUATOR_DEFAULTS.content_media_tags

        # 逐文件统计：剥标签正文字数 + 是否含实质媒体
        stats: list[dict[str, Any]] = []
        for f in files:
            raw = self._read_raw(f)
            body = file_to_text(f).strip()
            stats.append(
                {
                    "file": str(f.relative_to(output_dir)),
                    "body_chars": len(body),
                    "has_media": self._has_media(raw, f.suffix.lower(), media_tags),
                    "body": body,
                }
            )

        # 规则初筛：媒体页豁免（图集/表格式课件页正文天然短，不进疑似判定）；「包内
        # 典型正文量」的中位数用全体文件估计（媒体页的教学文字同样是真实产出，纳入
        # 基准使判定只更保守）。文件数 < 2 时无法稳健估计 → 放行（单文件包的占位由
        # LLM 软性评估兜底，宁缺毋滥）。
        text_pages = [s for s in stats if not s["has_media"]]
        suspects: list[dict[str, Any]] = []
        threshold: float | None = None
        median: float | None = None
        if len(stats) >= 2:
            median = statistics.median(s["body_chars"] for s in stats)
            threshold = median * ratio
            suspects = [s for s in text_pages if s["body_chars"] < threshold]

        # LLM 二次确认：剔除合法短页（封面/目录/过渡页）误报；不可用 → 保留规则判定
        empty_files: list[dict[str, Any]] = [
            dict(s, reason="正文量显著低于包内典型水平") for s in suspects
        ]
        verified_by_llm = False
        if suspects:
            confirmed = self._verify_with_llm(suspects, context)
            if confirmed is not None:
                verified_by_llm = True
                empty_files = confirmed

        elapsed = self._elapsed_ms(start)
        total = len(stats)
        empty_count = len(empty_files)
        max_empty_ratio = float(self.params.get("max_empty_ratio", 0.0))
        empty_ratio = empty_count / total if total else 0.0

        details: dict[str, Any] = {
            "total_files": total,
            "empty_count": empty_count,
            "empty_ratio": empty_ratio,
            "max_empty_ratio": max_empty_ratio,
            "adaptive_threshold": round(threshold, 1) if threshold is not None else None,
            "median_body_chars": round(median, 1) if median is not None else None,
            "verified_by_llm": verified_by_llm,
            "source_files": [{"filename": s["file"]} for s in empty_files],
        }

        if empty_count and empty_ratio > max_empty_ratio:
            desc = "；".join(
                f"{s['file']}（正文 {s['body_chars']} 字，包内中位数 {median:.0f}）"
                for s in empty_files[:5]
            )
            suffix = f"（共 {empty_count} 处）" if empty_count > 5 else ""
            reason = f"内容缺失: {empty_count}/{total} 个文件为空壳/占位: {desc}{suffix}"
            return self._make_result(
                status=EvalStatus.FAIL,
                score=0.0,
                reason=reason,
                details={**details, "empty_files": empty_files},
                duration_ms=elapsed,
            )

        if empty_count:
            reason = (
                f"发现 {empty_count} 个疑似空壳文件，未超过容忍比例 {max_empty_ratio:.0%}，判定通过"
            )
        else:
            thr_desc = (
                f"（自适应阈值 {threshold:.0f} 字 = 包内中位数 {median:.0f} × {ratio}）"
                if threshold
                else ""
            )
            reason = f"全部 {total} 个内容文件均有实质内容{thr_desc}"
        return self._make_result(
            status=EvalStatus.PASS,
            score=1.0,
            reason=reason,
            details=details,
            duration_ms=elapsed,
        )

    # ─── LLM 语义二次确认 ───

    def _verify_with_llm(
        self, suspects: list[dict[str, Any]], context: dict[str, Any]
    ) -> list[dict[str, Any]] | None:
        """批量调 content_verdict 裁定疑似文件，返回被确认为空壳的子集。

        LLM 不可用（无 orchestrator / 额度熔断 / 调用异常）返回 None，调用方保留
        规则判定（召回优先，与 info_accuracy 的 fact_verdict 降级语义一致）。
        """
        orchestrator = context.get("judge_orchestrator")
        evidence_dir = context.get("evidence_dir")
        if orchestrator is None or evidence_dir is None or context.get("llm_quota_exhausted"):
            return None

        max_chars = EVALUATOR_DEFAULTS.max_file_chars
        candidates = [
            {
                "index": i,
                "file": s["file"],
                "body_chars": s["body_chars"],
                "content": s["body"][:max_chars],
            }
            for i, s in enumerate(suspects)
        ]
        variables = {
            "title": context.get("task_input", {}).get("title", "未知标题"),
            "subject": context.get("task_input", {}).get("subject", "未知学科"),
            "candidates": candidates,
        }
        ev_dir = evidence_dir if isinstance(evidence_dir, Path) else Path(evidence_dir)
        try:
            verdict_prompt_id = self.params.get("verification_prompt_id", "content_verdict")
            _scores, record = orchestrator.judge(
                constraint_id=self.evaluator_id,
                sample_id=context.get("sample_id", "unknown"),
                template_id=verdict_prompt_id,
                variables=variables,
                evidence_dir=ev_dir,
                provider_name=self.params.get("llm_provider"),
                judge_id_suffix="content_verdict_0",
            )
        except Exception:
            logger.warning("content_verdict 二次确认失败，保留规则判定（召回优先）", exc_info=True)
            return None

        parsed = getattr(record, "parsed_scores", None) if record else None
        verdicts = parsed.get("verdicts", []) if isinstance(parsed, dict) else []
        verdict_map = {v.get("index"): v for v in verdicts if isinstance(v, dict) and "index" in v}
        confirmed: list[dict[str, Any]] = []
        for i, s in enumerate(suspects):
            v = verdict_map.get(i)
            # 缺裁定 → 默认空壳成立（召回优先，不漏报）
            is_empty = bool(v.get("is_empty", True)) if v else True
            s2 = dict(s)
            if v and v.get("reason"):
                s2["reason"] = v["reason"]
            if is_empty:
                confirmed.append(s2)
        return confirmed

    # ─── 工具 ───

    @staticmethod
    def _read_raw(path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return ""

    @staticmethod
    def _has_media(raw: str, suffix: str, media_tags: list[str]) -> bool:
        """是否存在实质媒体元素（图片/表格/音视频等）— 存在则不因正文短判空。"""
        if not raw:
            return False
        if suffix in (".html", ".htm"):
            return any(re.search(rf"<{tag}[\s>]", raw, re.IGNORECASE) for tag in media_tags)
        # Markdown：图片 / 表格行
        return bool(re.search(r"!\[", raw)) or bool(re.search(r"^\|.*\|$", raw, re.MULTILINE))

    @staticmethod
    def _elapsed_ms(start: float) -> float:
        return (time.monotonic() - start) * 1000
