"""chat 场景专属评估器（对话型 SUT：精确匹配 + 语义一致性 + 回答质量）。

- ``chat.answer_exact``: expected.answer 在回答文本中命中（规则式，HARD_SCORE 二值）
- ``chat.answer_consistency``: 对照 expected.reference 的语义一致性 LLM Judge
  （主张级核对：遗漏部分扣分、矛盾重扣；评"说得是否一致"而非"说得好不好"）
- ``chat.answer_quality``: 回答质量 LLM Judge（对照任务指令与 must_mention 要点）

由 chat 场景包 ``manifest.entry_points.evaluators`` 在加载时导入注册。
"""

from __future__ import annotations

import re
import time
from typing import Any

from agent_eval.core.types import ConstraintTier, EvalMethod, EvalStatus
from agent_eval.evaluation.base import BaseEvaluator
from agent_eval.evaluation.evaluators.quality_evaluators import BaseLLMJudgeEvaluator
from agent_eval.evaluation.registry import registry
from agent_eval.evaluation.text_utils import get_output_dir as _get_output_dir


def _collect_answer_text(sample: Any) -> str:
    """从 output 目录收集回答文本（answer.md 等纯文本，不带文件边界标记）。"""
    output_dir = _get_output_dir(sample)
    if output_dir is None or not output_dir.exists():
        return ""
    parts: list[str] = []
    for ext in ("*.md", "*.markdown", "*.txt"):
        for f in sorted(output_dir.rglob(ext)):
            parts.append(f.read_text(encoding="utf-8", errors="ignore"))
    return "\n\n".join(parts)


@registry.register("chat.answer_exact")
class ChatAnswerExactEvaluator(BaseEvaluator):
    """答案精确匹配 — expected.answer 在回答文本中命中（数字按词边界）。"""

    evaluator_id = "chat.answer_exact"
    name = "答案精确匹配"
    tier = ConstraintTier.HARD_SCORE
    method = EvalMethod.RULE

    def evaluate(self, sample: Any, context: dict[str, Any]) -> Any:
        start = time.monotonic()
        expected = context.get("task_expected") or {}
        answer = expected.get("answer")
        if answer is None:
            return self._make_result(
                status=EvalStatus.SKIP,
                score=0.0,
                reason="任务未声明 expected.answer，跳过",
                duration_ms=(time.monotonic() - start) * 1000,
            )
        text = _collect_answer_text(sample)
        # 纯数字用词边界匹配（避免 13/30 命中 3）；其他按子串
        answer_str = str(answer)
        if re.fullmatch(r"-?\d+(\.\d+)?", answer_str):
            hit = re.search(rf"(?<![\d.]){re.escape(answer_str)}(?![\d.])", text) is not None
        else:
            hit = answer_str in text
        if hit:
            return self._make_result(
                status=EvalStatus.PASS,
                score=1.0,
                reason=f"expected.answer={answer_str} 命中",
                duration_ms=(time.monotonic() - start) * 1000,
            )
        return self._make_result(
            status=EvalStatus.FAIL,
            score=0.0,
            reason=f"expected.answer={answer_str} 未在回答中命中",
            duration_ms=(time.monotonic() - start) * 1000,
        )


@registry.register("chat.answer_quality")
class ChatAnswerQualityEvaluator(BaseLLMJudgeEvaluator):
    """回答质量评估 — LLM 对照任务指令与预期要点，评正确性/切题性/完整性。"""

    evaluator_id = "chat.answer_quality"
    name = "回答质量"
    tier = ConstraintTier.SOFT
    method = EvalMethod.LLM_JUDGE
    template_id = "chat_answer_quality"

    def _build_variables(self, text: str, context: dict[str, Any]) -> dict[str, Any]:
        task_input = context.get("task_input") or {}
        expected = context.get("task_expected") or {}
        must_mention = expected.get("must_mention") or []
        return {
            "content": text,
            "instruction": task_input.get("instruction", "未提供任务指令"),
            "must_mention": "\n".join(f"- {m}" for m in must_mention) or "无",
        }


@registry.register("chat.answer_consistency")
class ChatAnswerConsistencyEvaluator(BaseLLMJudgeEvaluator):
    """答案语义一致性 — 对照 expected.reference，主张级核对（遗漏扣分、矛盾重扣）。

    与 answer_quality 互补：quality 问"回答好不好"，本评估器只问"与参考答案
    说的是否一致"——角色认知/事实类任务的核心闸门。未声明 reference 时跳过。
    """

    evaluator_id = "chat.answer_consistency"
    name = "答案语义一致性"
    tier = ConstraintTier.SOFT
    method = EvalMethod.LLM_JUDGE
    template_id = "chat_answer_consistency"

    def evaluate(self, sample: Any, context: dict[str, Any]) -> Any:
        """未声明 expected.reference 时 SKIP（不计分），否则走 LLM Judge 基类流程。"""
        import time

        expected = context.get("task_expected") or {}
        if expected.get("reference") is None:
            start = time.monotonic()
            return self._make_result(
                status=EvalStatus.SKIP,
                score=0.0,
                reason="任务未声明 expected.reference，跳过",
                duration_ms=(time.monotonic() - start) * 1000,
            )
        return super().evaluate(sample, context)

    def _build_variables(self, text: str, context: dict[str, Any]) -> dict[str, Any]:
        task_input = context.get("task_input") or {}
        expected = context.get("task_expected") or {}
        return {
            "content": text,
            "instruction": task_input.get("instruction", "未提供任务指令"),
            "reference": str(expected.get("reference", "")),
        }


def register() -> list[str]:
    """entry_points 入口：模块导入即完成 chat.* 注册，返回已注册 id。"""
    return ["chat.answer_exact", "chat.answer_consistency", "chat.answer_quality"]
