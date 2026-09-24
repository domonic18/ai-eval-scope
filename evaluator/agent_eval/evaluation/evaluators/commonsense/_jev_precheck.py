"""info_accuracy Phase 2.5 mixin — Jev 高置信误触预筛。

组合进 ``InfoAccuracyEvaluator``：在规则 error 候选送 fact_verdict 复核前，
经 Jev Noul 原语剔除高置信误触。**filter-only**：只有剔除权、无确认权；
被剔除候选保留在 findings（写审计字段可溯），仅不进 rule_errors 一票否决。
未启用（jev_enabled=False 默认 / jev 线路未注入）时与直构候选完全一致。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent_eval.config import EVALUATOR_DEFAULTS
from agent_eval.evaluation.evaluators.commonsense._shared import logger
from agent_eval.evaluation.jev_filter import JevFactFilter

#: 过滤阶段证据文件名（per-sample evidence 目录内，对齐 judge_* 命名族）
JEV_EVIDENCE_FILENAME = "jev_fact_filter.json"


class InfoAccuracyJevPrecheck:
    """Jev 预筛（Phase 2.5）——组合用 mixin。

    依赖组合主体（InfoAccuracyLLMVerify）提供的成员：
    params / _extract_finding_context。
    """

    # 组合主体成员声明（仅注解，零运行时）——供类型检查器解析 self.* 引用
    params: dict[str, Any]
    _extract_finding_context: Any

    def _apply_jev_filter(
        self,
        error_findings: list[dict[str, Any]],
        file_texts: dict[str, str],
        context: dict[str, Any],
        evidence_dir: Any,
    ) -> list[dict[str, Any]]:
        """构建送 fact_verdict 复核的候选列表（Jev 启用时先剔除高置信误触）。

        候选 index 保持 error_findings 原下标（verdict_map 回填依赖此约定）；
        审计字段（_jev_probability/_jev_filtered）就地写回 finding。
        """
        candidates = [
            {
                "index": i,
                "file": f.get("file", ""),
                "message": f.get("message", ""),
                "context": self._extract_finding_context(f, file_texts),
            }
            for i, f in enumerate(error_findings)
        ]
        client = context.get("jev_client")
        enabled = self.params.get("jev_enabled", EVALUATOR_DEFAULTS.jev_enabled)
        if client is None or not enabled or not candidates:
            return candidates
        jev_filter = JevFactFilter(
            client,
            drop_below=self.params.get("jev_drop_below", EVALUATOR_DEFAULTS.jev_drop_below),
            max_concurrency=self.params.get(
                "jev_max_concurrency", EVALUATOR_DEFAULTS.jev_max_concurrency
            ),
            instructions=self.params.get("jev_question_template"),
        )
        try:
            report = jev_filter.run(candidates)
        except Exception:
            # 过滤层自身异常（非 JevError 的意外错误）→ 全量升级，语义等价未启用
            logger.warning("jev 过滤层异常 → 全量升级 LLM（召回优先）", exc_info=True)
            return candidates
        for item in report.items:
            finding = error_findings[item["index"]]
            if item["probability"] is not None:
                finding["_jev_probability"] = item["probability"]
            if item["decision"] == "drop":
                finding["_jev_filtered"] = True
        self._write_jev_evidence(report, evidence_dir)
        dropped = report.counts.get("dropped", 0)
        logger.info(
            "jev 误触过滤完成",
            total=report.counts.get("total", 0),
            dropped=dropped,
            escalated=report.counts.get("escalated", 0),
            model=report.model,
        )
        return [c for c in candidates if not error_findings[c["index"]].get("_jev_filtered")]

    @staticmethod
    def _write_jev_evidence(report: Any, evidence_dir: Any) -> None:
        """过滤阶段证据落盘（失败仅 warning 不阻断，对齐证据链容错惯例）。"""
        if evidence_dir is None:
            return
        try:
            ev_dir = Path(evidence_dir) if not isinstance(evidence_dir, Path) else evidence_dir
            ev_dir.mkdir(parents=True, exist_ok=True)
            (ev_dir / JEV_EVIDENCE_FILENAME).write_text(
                json.dumps(report.to_evidence(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            logger.warning("jev_fact_filter.json 落盘失败（不阻断评估）", exc_info=True)
