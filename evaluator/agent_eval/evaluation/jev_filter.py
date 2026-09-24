"""Jev 高置信误触过滤层 — 规则 error 候选送 LLM 复核前的预筛（策略层）。

在 commonsense.info_accuracy 的 fact_verdict 批量复核前，用 Jev Noul 原语
（state + 是/否问题 → P(yes)）做纯语义二值预判：P(真错误) < drop_below 的
高置信误触直接剔除。**filter-only 语义**：Jev 只有剔除权、无确认权——真错误
的最终裁定与解释一律由 LLM 产出。

降级语义（召回优先不变式）：
- 未启用 / jev 线路未注入 → 不调 Jev，全量走 LLM（与未启用逐字节一致）
- 单候选调用/解析失败 → 该候选 ESCALATE（不 DROP）
- p ∈ [drop_below, 1.0] → ESCALATE → LLM 终审

阈值 drop_below=0.50 为对拍校准值（误触带 ≤0.29 / 真错误带 ≥0.79 空谷定标）；
任何阈值或模型版本变更须重跑对拍。候选 context 来自被评课件文本，判定结果
只影响「是否送 LLM」，最坏后果=漏过滤（无提权面）。
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

import structlog

from agent_eval.llm.jev import JevError, NoulQuestion

logger = structlog.get_logger("evaluation.jev")

#: 默认问题正文（对齐 fact_verdict 判定原则：成立需「原文确实陈述该事实，
#: 且该陈述确实错误」；语用框架——否定标记/反例/假设/纠错表述——不算成立）
DEFAULT_INSTRUCTIONS = (
    "判定课件文本中被标记的疑似事实错误是否真实成立。成立=true 需同时满足："
    "原文确实做出了该事实/数值/关系的陈述，且该陈述内容确实错误。"
    "若标记源于上下文误读（跨实体误配、编号误抓）或语用框架"
    "（✗ 等否定标记、反例、'如果…' 假设、纠错示范表述），则判不成立。"
)
#: criteria 双侧定义（是/否各自语义边界，固定不随模板覆盖）
DEFAULT_CRITERIA: dict[str, str] = {
    "true": "原文确实做出该陈述，且陈述内容确实错误——事实性错误成立",
    "false": "陈述实际正确、原文并无此陈述、或标记源于误读/否定/假设等语用框架——误触",
}


@dataclass
class JevStageReport:
    """单次过滤阶段的审计报告（供 jev_fact_filter.json 落盘；不含任何凭证）。"""

    enabled: bool = True
    model: str = ""  # 服务端 resolved 快照，缺 resolved 时回退配置 slug
    drop_below: float = 0.50
    counts: dict[str, int] = field(default_factory=dict)  # total / dropped / escalated
    items: list[dict[str, Any]] = field(default_factory=list)
    # item: {index, probability(失败为 None), decision(drop|escalate), latency_ms}

    def to_evidence(self) -> dict[str, Any]:
        """证据文件 payload（问题原文截断存储，见 items 外的 question 字段由调用方补）。"""
        return {
            "enabled": self.enabled,
            "model": self.model,
            "drop_below": self.drop_below,
            "counts": dict(self.counts),
            "items": [dict(item) for item in self.items],
        }


class JevFactFilter:
    """规则 error 候选的 Jev 预筛器（filter-only：产出 DROP/ESCALATE 分带）。

    构造注入 JevClient（单测经替身 client 注入，禁联网纪律不破）；httpx.Client
    官方支持多线程共享，run() 内 ThreadPoolExecutor 并发判定共用单实例。
    """

    def __init__(
        self,
        client: Any,
        drop_below: float = 0.50,
        max_concurrency: int = 8,
        instructions: str | None = None,
        criteria: Mapping[str, str] | None = None,
    ) -> None:
        """
        Args:
            client: JevClient 实例（或同形替身：noul(question, state) -> JevAnswer）。
            drop_below: P(真错误) 低于此值判高置信误触 → 剔除。
            max_concurrency: Noul 并发上限。
            instructions: 问题正文覆盖（None=内置默认）。
            criteria: 双侧定义覆盖（None=内置默认）。
        """
        self._client = client
        self._drop_below = drop_below
        self._max_concurrency = max(1, max_concurrency)
        self._instructions = instructions or DEFAULT_INSTRUCTIONS
        self._criteria = dict(criteria) if criteria else dict(DEFAULT_CRITERIA)

    def run(self, candidates: list[dict[str, Any]]) -> JevStageReport:
        """并发判定候选集合，产出分带报告。候选形态：{index, file, message, context}。

        逐候选异常（JevError）吞并 → 该候选 ESCALATE；本方法不主动抛
        JevError（整体故障等价于全量升级，语义与未启用一致）。
        """
        question = NoulQuestion(
            name="is_real_error", instructions=self._instructions, criteria=self._criteria
        )
        items: list[dict[str, Any]] = [{}] * len(candidates)
        with ThreadPoolExecutor(max_workers=self._max_concurrency) as ex:
            futures = {ex.submit(self._judge_one, c, question): i for i, c in enumerate(candidates)}
            for fut, i in futures.items():
                items[i] = fut.result()
        dropped = sum(1 for it in items if it.get("decision") == "drop")
        model = next((it["model"] for it in items if it.get("model")), "") or self._client.model
        return JevStageReport(
            model=model,
            drop_below=self._drop_below,
            counts={"total": len(items), "dropped": dropped, "escalated": len(items) - dropped},
            items=items,
        )

    def _judge_one(self, candidate: dict[str, Any], question: NoulQuestion) -> dict[str, Any]:
        """单候选判定（异常吞并为升级项；延迟逐候选实测）。"""
        state = {"text": candidate.get("context", ""), "claim": candidate.get("message", "")}
        start = time.monotonic()
        try:
            ans = self._client.noul(question, state)
        except JevError as e:
            logger.warning(
                "jev 单候选判定失败 → 升级 LLM（召回优先）",
                index=candidate.get("index"),
                error=str(e),
            )
            return {
                "index": candidate.get("index"),
                "probability": None,
                "decision": "escalate",
                "latency_ms": round((time.monotonic() - start) * 1000, 1),
            }
        latency = round((time.monotonic() - start) * 1000, 1)
        decision = "drop" if ans.p_yes < self._drop_below else "escalate"
        return {
            "index": candidate.get("index"),
            "probability": ans.p_yes,
            "decision": decision,
            "latency_ms": latency,
            "model": ans.model,
        }
