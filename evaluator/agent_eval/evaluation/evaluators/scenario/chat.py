"""chat 场景专属评估器（对话型 SUT：精确匹配 + 语义一致性 + 回答质量）。

- ``chat.answer_exact``: 两阶段精确匹配——LLM 提取 SUT 最终答案 → 规则式比对
  （Phase 1 理解、Phase 2 确定；无 hardcode 模式，任意语言/领域通用）
- ``chat.answer_consistency``: 对照 expected.reference 的语义一致性 LLM Judge
  （主张级核对：遗漏部分扣分、矛盾重扣；评"说得是否一致"而非"说得好不好"）
- ``chat.answer_quality``: 回答质量 LLM Judge（对照任务指令与 must_mention 要点）

由 chat 场景包 ``manifest.entry_points.evaluators`` 在加载时导入注册。
"""

from __future__ import annotations

import json
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


def _exact_match(extracted: str, expected: str) -> bool:
    """Phase 2：确定性的精确比对（数字词边界 / 文本子串）。"""
    if re.fullmatch(r"-?\d+(\.\d+)?", expected):
        return re.search(rf"(?<![\d.]){re.escape(expected)}(?![\d.])", extracted) is not None
    return expected in extracted


@registry.register("chat.answer_exact")
class ChatAnswerExactEvaluator(BaseEvaluator):
    """答案精确匹配 — 两阶段：LLM 提取最终答案 → 规则式比对。

    Phase 1（LLM）：从自由文本中提取 SUT 最终确认的答案值——通过上下文理解
    区分主结论与修正假设/引用/中间步骤（chat_answer_extract.yaml，通用指令）。
    Phase 2（规则）：extracted 与 expected.answer 的确定性比对。

    LLM Judge 不可用（离线模式）时退化为全文词边界搜索（已知局限：
    可能命中修正假设中的值——文档声明，在线场景推荐启用 Judge）。
    """

    evaluator_id = "chat.answer_exact"
    name = "答案精确匹配"
    tier = ConstraintTier.HARD_SCORE
    method = EvalMethod.RULE  # 比对阶段为规则式（HARD_SCORE 二值保留）
    template_id = "chat_answer_extract"  # Phase 1 提取模板

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
        answer_str = str(answer)

        # Phase 1：LLM 提取最终答案（不可用 → 回退全文）
        orchestrator = context.get("judge_orchestrator")
        if orchestrator is not None:
            extracted = self._extract_answer(text, context, orchestrator)
            phase1 = "LLM 提取"
            if extracted is None:
                return self._make_result(
                    status=EvalStatus.FAIL,
                    score=0.0,
                    reason=f"LLM 判定回答未给出明确答案（expected={answer_str}）",
                    duration_ms=(time.monotonic() - start) * 1000,
                )
        else:
            extracted = text
            phase1 = "全文搜索（离线退化）"

        # Phase 2：确定性比对
        if _exact_match(extracted, answer_str):
            return self._make_result(
                status=EvalStatus.PASS,
                score=1.0,
                reason=f"expected.answer={answer_str} 命中（{phase1}：{extracted[:50]}）",
                duration_ms=(time.monotonic() - start) * 1000,
            )
        return self._make_result(
            status=EvalStatus.FAIL,
            score=0.0,
            reason=f"expected.answer={answer_str} ≠ 提取答案 {extracted[:50]!r}（{phase1}）",
            duration_ms=(time.monotonic() - start) * 1000,
        )

    def _extract_answer(self, text: str, context: dict[str, Any], orchestrator: Any) -> str | None:
        """Phase 1：直接调 LLM（经 orchestrator.pool/templates，绕过评分管线）提取最终答案。

        orchestrator.judge() 是维度评分管线（_coerce_score 仅接受数值），
        不适合字符串值提取——此处用 pool 直调 LLM，复用模板渲染与 provider 选择。
        """
        task_input = context.get("task_input") or {}
        variables = {
            "content": text,
            "instruction": task_input.get("instruction", "未提供任务指令"),
        }
        try:
            from agent_eval.llm.models import Message

            # 从 orchestrator 拿模板并渲染（与 judge() 同一管线）
            template = orchestrator.templates.get(
                context.get("scenario_id", "chat"), self._effective_template_id
            )
            system_prompt, user_prompt = orchestrator.templates.render(template, variables)

            # 经 pool 直调 LLM（复用同一 provider/配置/降级链路）
            client = orchestrator.pool.get(context.get("llm_provider"))
            response = client.chat(
                [
                    Message(role="system", content=system_prompt),
                    Message(role="user", content=user_prompt),
                ]
            )
            return self._parse_extracted(response.content)
        except Exception:  # noqa: BLE001 — LLM 提取失败回退全文
            return text

    @staticmethod
    def _render_user_prompt(template_str: str, variables: dict[str, Any]) -> str:
        """Jinja2 渲染（与 FilePromptStore 同款引擎）。"""
        from jinja2 import Template

        return Template(template_str).render(**variables)

    @staticmethod
    def _parse_extracted(raw: Any) -> str | None:
        """解析 LLM 原文：完整 JSON → 含 answer 键的 JSON 片段 → 裸值；null → None。"""
        if raw is None:
            return None
        s = str(raw).strip()
        if not s or s.lower() == "null":
            return None
        try:
            data = json.loads(s)
            if isinstance(data, dict):
                val = data.get("answer")
                return None if val is None else str(val).strip()
            return str(data).strip()
        except (json.JSONDecodeError, ValueError):
            pass
        m = re.search(r'\{[^{}]*"answer"[^{}]*\}', s)
        if m:
            try:
                data = json.loads(m.group())
                val = data.get("answer")
                return None if val is None else str(val).strip()
            except (json.JSONDecodeError, ValueError):
                pass
        return s

    @property
    def _effective_template_id(self) -> str:
        """优先规则层 prompt_id，回退类默认。"""
        return self.params.get("prompt_id") or self.template_id


@registry.register("chat.answer_quality")
class ChatAnswerQualityEvaluator(BaseLLMJudgeEvaluator):
    """回答质量评估 — LLM 对照任务指令与预期要点，评正确性/切题性/完整性。"""

    evaluator_id = "chat.answer_quality"
    name = "回答质量"
    tier = ConstraintTier.SOFT
    method = EvalMethod.LLM_JUDGE
    template_id = "chat_answer_quality"
    # 判官模板变量契约（落盘对账用，与 _build_variables 保持一致）：包内
    # user_prompt_template 只能使用这些变量——写错运行时 StrictUndefined 必报
    # 「模板渲染失败，变量缺失」→ 该规则 0 分（实测 agent-security 包事故）
    prompt_variables = frozenset({"content", "instruction", "must_mention"})

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
    # 变量契约同 answer_quality（见其注释）；reference 来自 expected.reference
    prompt_variables = frozenset({"content", "instruction", "reference"})

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
