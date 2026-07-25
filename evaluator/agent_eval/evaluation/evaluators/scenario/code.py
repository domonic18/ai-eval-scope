"""code 场景专属评估器（阶段 4 示例：随场景包 entry_points 注册）。

代码生成场景的 LLM Judge 评估器：
- ``code.correctness``: 代码正确性（LLM_JUDGE，prompt=code_correctness）
- ``code.style``: 代码风格（LLM_JUDGE，prompt=code_style）

继承通用 :class:`BaseLLMJudgeEvaluator`（prompt 驱动），仅声明 evaluator_id/tier/template_id。
本模块由 code 场景包 ``manifest.entry_points.evaluators`` 在加载时导入，
``@registry.register`` 完成 code.* 注册。
"""

from __future__ import annotations

from agent_eval.core.types import ConstraintTier, EvalMethod
from agent_eval.evaluation.evaluators.quality_evaluators import BaseLLMJudgeEvaluator
from agent_eval.evaluation.registry import registry


@registry.register("code.correctness")
class CodeCorrectnessEvaluator(BaseLLMJudgeEvaluator):
    """代码正确性评估 — LLM 评审代码逻辑正确性、边界处理与可运行性。"""

    evaluator_id = "code.correctness"
    name = "代码正确性"
    tier = ConstraintTier.SOFT
    method = EvalMethod.LLM_JUDGE
    template_id = "code_correctness"


@registry.register("code.style")
class CodeStyleEvaluator(BaseLLMJudgeEvaluator):
    """代码风格评估 — LLM 评审代码可读性、命名与结构规范性（与正确性正交）。"""

    evaluator_id = "code.style"
    name = "代码风格"
    tier = ConstraintTier.SOFT
    method = EvalMethod.LLM_JUDGE
    template_id = "code_style"


def register() -> list[str]:
    """entry_points 入口（幂等）。

    模块导入时 ``@registry.register`` 装饰器已完成 code.* 注册（Python 模块缓存保证
    重复导入不二次注册）；本函数仅返回已注册 id，供 manifest
    ``entry_points.evaluators: "...scenario.code:register"`` 调用，重复调用安全。
    """
    return ["code.correctness", "code.style"]
