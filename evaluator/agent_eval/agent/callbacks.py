"""LangGraph 回调 — 预算护栏与会话日志注入（arch/03 §7a.6 v4.6）。

BudgetGuard / SessionLogCallback 为鸭子类型回调处理器（实现 LangChain
回调协议的 on_llm_end / on_tool_start / on_tool_end 方法，无需继承
langchain_core 基类），经 ainvoke(config={"callbacks": [...]}) 注入
DeepAgents 图执行。
"""

from __future__ import annotations

from typing import Any

from agent_eval.agent.hooks import BudgetController, SessionLogger
from agent_eval.agent.sut_tools import HTTP_RAW_MAX_CHARS
from agent_eval.core.exceptions import BudgetExceededError


def _extract_usage(response: Any) -> dict[str, int] | None:
    """从 LLMResult 兼容形态提取 token 用量。

    依次尝试（LangChain 新旧版本 / dict 兼容）：
    1. generations[i][j].message.usage_metadata（ChatModel 新式）
    2. response["usage_metadata"]（dict 形态）
    3. response.llm_output["token_usage"]（旧式 LLMResult）
    """
    for generation in getattr(response, "generations", []) or []:
        if isinstance(generation, list):
            for chunk in generation:
                message = getattr(chunk, "message", None)
                usage = getattr(message, "usage_metadata", None)
                if isinstance(usage, dict):
                    return usage
    if isinstance(response, dict):
        usage = response.get("usage_metadata")
        if isinstance(usage, dict):
            return usage
        llm_output = response.get("llm_output") or {}
        if isinstance(llm_output, dict):
            return llm_output.get("token_usage")
    llm_output = getattr(response, "llm_output", None)
    if isinstance(llm_output, dict):
        return llm_output.get("token_usage")
    return None


def _normalize_usage(usage: dict[str, int] | None) -> tuple[int, int]:
    """归一化 token 用量为 (input_tokens, output_tokens)。

    新式 usage_metadata: input_tokens/output_tokens；
    旧式 token_usage: prompt_tokens/completion_tokens。
    """
    if not usage:
        return 0, 0
    input_tokens = usage.get("input_tokens", usage.get("prompt_tokens", 0)) or 0
    output_tokens = usage.get("output_tokens", usage.get("completion_tokens", 0)) or 0
    return int(input_tokens), int(output_tokens)


class BudgetGuard:
    """预算护栏回调：on_llm_end 累计 token/成本，超限抛 BudgetExceededError 终止图执行。

    成本估算依赖可选 pricing 配置（{"input_per_1k": x, "output_per_1k": y}，
    可来自 provider extra_params.pricing）；未配置时仅累计 token，成本记 0。
    """

    def __init__(
        self,
        max_budget_usd: float,
        controller: BudgetController | None = None,
        *,
        pricing: dict[str, float] | None = None,
    ) -> None:
        self.controller = controller or BudgetController(max_budget_usd)
        self.pricing = pricing or {}
        self.llm_calls = 0

    def on_llm_end(self, response: Any, **kwargs: Any) -> None:
        """LLM 调用结束：计量 token/成本并检查预算。"""
        self.llm_calls += 1
        input_tokens, output_tokens = _normalize_usage(_extract_usage(response))
        cost_usd = 0.0
        if self.pricing:
            cost_usd = input_tokens / 1000 * self.pricing.get(
                "input_per_1k", 0.0
            ) + output_tokens / 1000 * self.pricing.get("output_per_1k", 0.0)
        state = self.controller.record(cost_usd, input_tokens + output_tokens)
        if state == "exceeded":
            raise BudgetExceededError(
                f"Agent 执行超出预算: 已花费 ${self.controller.spent_usd:.4f} "
                f"(上限 ${self.controller.max_budget_usd})",
            )

    @property
    def spent_usd(self) -> float:
        """当前累计成本。"""
        return self.controller.spent_usd

    @property
    def total_tokens(self) -> int:
        """当前累计 token。"""
        return self.controller.total_tokens


class SessionLogCallback:
    """会话日志回调：on_tool_start/on_tool_end → SessionLogger 结构化日志。"""

    def __init__(self, logger: SessionLogger) -> None:
        self.logger = logger
        # run_id → (call_id, tool_name)，on_tool_end 无工具名，靠配对还原
        self._active: dict[str, tuple[str, str]] = {}

    def on_tool_start(
        self,
        serialized: dict[str, Any] | None,
        input_str: str,
        *,
        run_id: Any = None,
        inputs: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        """工具调用开始：记录 tool_call 事件。"""
        name = ""
        if isinstance(serialized, dict):
            name = serialized.get("name") or ""
        tool_input = dict(inputs or {})
        if not tool_input and input_str:
            tool_input = {"input": input_str[:HTTP_RAW_MAX_CHARS]}
        call_id = self.logger.log_tool_call(name or "unknown", tool_input)
        self._active[str(run_id)] = (call_id, name or "unknown")

    def on_tool_end(self, output: Any, *, run_id: Any = None, **kwargs: Any) -> None:
        """工具调用结束：记录 tool_result 事件。"""
        call_id, name = self._active.pop(str(run_id), (None, "unknown"))
        summary = {"output": str(output)[:HTTP_RAW_MAX_CHARS]}
        self.logger.log_tool_result(name, summary, call_id, status="success")

    def on_tool_error(
        self, error: BaseException | None, *, run_id: Any = None, **kwargs: Any
    ) -> None:
        """工具调用异常：记录 error 状态的 tool_result。"""
        call_id, name = self._active.pop(str(run_id), (None, "unknown"))
        self.logger.log_tool_result(name, {"error": str(error)}, call_id, status="error")
