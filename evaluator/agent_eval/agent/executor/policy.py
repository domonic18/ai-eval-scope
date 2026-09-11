"""交互预算解析（arch/16 §4.1 P1 声明式预算）。

InteractionPolicy 声明「允许与 SUT 发生多少次交互」——一等预算面；
recursion_limit 由 :func:`derive_recursion_limit` 自动推导为保险丝，
只兜图失控、不参与正常控制，结束预算逐 run 人工调参（max_turns 跑步机）。

继承链（高 → 低）：

1. ``task.constraints["interaction_policy"]``（dict，部分覆盖）
2. ``task_set.interaction_policy``
3. 全局缺省（``INTERACTION_POLICY_DEFAULTS``）

非法子键静默回退上层——与 ``_resolve_max_turns``「兜底取值」惯例一致；
组合后违约（如任务级 nudges 超出任务集 total-dispatch 余量）整层回退。
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from agent_eval.config import INTERACTION_POLICY_DEFAULTS
from agent_eval.execution.models import InteractionPolicy, Task, TaskSet

# 双轨迁移注记（Phase 2 降格 max_turns 配置链前保留）
LEGACY_MAX_TURNS_NOTE = (
    "constraints.max_turns 双轨迁移：声明了 interaction_policy 的任务以 policy "
    "为准（max_turns 忽略）；未声明的任务沿用 _resolve_max_turns 旧链。"
)

# 各字段的单键合法性判据（交叉校验交给最终模型构造）
_INT_FIELDS = {"sut_calls_total", "dispatch", "state_polls", "downloads"}
_NUDGES_FIELD = "nudges"
_FLOAT_FIELDS = {"nudge_backoff_s", "wall_clock_deadline_s"}


def _valid_value(key: str, value: Any) -> bool:
    """单键类型与取值域校验（不含跨字段约束）。"""
    if key in _INT_FIELDS:
        return isinstance(value, int) and not isinstance(value, bool) and value > 0
    if key == _NUDGES_FIELD:
        return isinstance(value, int) and not isinstance(value, bool) and value >= 0
    if key in _FLOAT_FIELDS:
        return isinstance(value, int | float) and not isinstance(value, bool) and value > 0
    return False


def _apply_partial(base: dict[str, Any], overrides: Any) -> dict[str, Any]:
    """把部分覆盖合并进 base dict——非法子键静默忽略（保底上层值）。"""
    if not isinstance(overrides, dict):
        return base
    for key, value in overrides.items():
        if key in InteractionPolicy.model_fields and _valid_value(key, value):
            base[key] = value
    return base


def resolve_interaction_policy(
    task: Task,
    task_set: TaskSet | None = None,
) -> InteractionPolicy:
    """解析任务生效的交互预算——继承链 task 级部分覆盖 > 任务集级 > 全局缺省。

    任一层声明非法（类型错 / 取值越界 / 组合违约）即静默回退上层，
    绝不让预算解析失败挡住任务执行——闸门兜的是运行期额度，不是配置期报错。
    """
    # 全局缺省为底
    merged: dict[str, Any] = {
        field: getattr(INTERACTION_POLICY_DEFAULTS, field)
        for field in InteractionPolicy.model_fields
    }
    # 任务集级整体声明（已过模型校验，直接展开）
    if task_set is not None and task_set.interaction_policy is not None:
        merged.update(task_set.interaction_policy.model_dump())
    upper = dict(merged)
    # 任务级部分覆盖
    _apply_partial(merged, task.constraints.get("interaction_policy"))
    try:
        return InteractionPolicy(**merged)
    except ValidationError:
        # 组合后违约（如任务级 nudges 超出任务集 total-dispatch 余量）——
        # 任务层整体回退上层
        return InteractionPolicy(**upper)


def declares_interaction_policy(task: Task, task_set: TaskSet | None = None) -> bool:
    """任务 / 任务集是否显式声明了 interaction_policy（双轨迁移判据）。"""
    if task_set is not None and task_set.interaction_policy is not None:
        return True
    return isinstance(task.constraints.get("interaction_policy"), dict)


def derive_recursion_limit(policy: InteractionPolicy) -> int:
    """由语义预算推导图保险丝——宽于正常消耗，只兜失控不参与控制。

    语义步 = SUT 交互 + 下载 + 取证轮询（全额计入）+ 固定余量
    （取证整理 / write_package / read_file 等非 SUT 交互步）；
    ×2 对齐「1 轮 ≈ 2 step（模型 + 工具节点）」的图步进假设。

    轮询不可折算：每轮 poll 都是完整的模型决策 + 工具执行（实测定级
    run 20260911_073626：等待 SUT 分段后台生成合法轮询 21 次，1/10 折算
    使保险丝 50 步在语义预算 21/60 时熔断——违背「宽于语义预算」不变量）。
    保险丝兜的是无限失控，158 与 50 同样兜得住，晚熔断不损失防线。
    """
    semantic_steps = policy.sut_calls_total + policy.downloads + policy.state_polls + 6
    return semantic_steps * 2
