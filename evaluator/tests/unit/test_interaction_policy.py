"""InteractionPolicy 预算模型与解析单测（arch/16 §4.1 P1 声明式预算）。"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from agent_eval.agent.executor.policy import (
    derive_recursion_limit,
    resolve_interaction_policy,
)
from agent_eval.config import INTERACTION_POLICY_DEFAULTS
from agent_eval.execution.models import InteractionPolicy, Task, TaskSet


def _task(policy: dict | None = None) -> Task:
    constraints = {"interaction_policy": policy} if policy is not None else {}
    return Task(id="t1", input={"topic": "x"}, constraints=constraints)


def _task_set(policy: InteractionPolicy | dict | None = None) -> TaskSet:
    payload: dict = {
        "id": "ts1",
        "name": "任务集一",
        "tasks": [],
    }
    if policy is not None:
        payload["interaction_policy"] = policy
    return TaskSet(**payload)


class TestInteractionPolicyModel:
    """InteractionPolicy 模型校验。"""

    def test_defaults_from_config(self) -> None:
        policy = InteractionPolicy()
        assert policy.sut_calls_total == INTERACTION_POLICY_DEFAULTS.sut_calls_total == 8
        assert policy.dispatch == 1
        assert policy.nudges == 2
        assert policy.state_polls == 60
        assert policy.downloads == 5
        assert policy.nudge_backoff_s == 30.0
        assert policy.wall_clock_deadline_s == 1500.0

    def test_nonpositive_counts_rejected(self) -> None:
        for field in ("sut_calls_total", "dispatch", "state_polls", "downloads"):
            with pytest.raises(ValidationError):
                InteractionPolicy(**{field: 0})

    def test_negative_nudges_rejected(self) -> None:
        with pytest.raises(ValidationError):
            InteractionPolicy(nudges=-1)

    def test_nudges_within_total_dispatch(self) -> None:
        # nudges(5) <= total(8) - dispatch(1) = 7 合法
        assert InteractionPolicy(nudges=5).nudges == 5
        # nudges 越过 total-dispatch 余量违约
        with pytest.raises(ValidationError, match="sut_calls_total - dispatch"):
            InteractionPolicy(nudges=8)

    def test_task_set_accepts_policy_from_yaml_dict(self) -> None:
        """任务集 YAML 顶层 interaction_policy dict 自动 coerced 成模型。"""
        task_set = _task_set({"nudges": 3, "state_polls": 30})
        assert isinstance(task_set.interaction_policy, InteractionPolicy)
        assert task_set.interaction_policy.nudges == 3
        assert task_set.interaction_policy.state_polls == 30
        # 未声明键落缺省
        assert task_set.interaction_policy.sut_calls_total == 8


class TestResolveInteractionPolicy:
    """继承链解析：任务级部分覆盖 > 任务集级 > 全局缺省。"""

    def test_defaults_when_no_declaration(self) -> None:
        policy = resolve_interaction_policy(_task())
        assert policy == InteractionPolicy()

    def test_task_set_level_applies(self) -> None:
        policy = resolve_interaction_policy(_task(), _task_set({"nudges": 5, "downloads": 2}))
        assert policy.nudges == 5
        assert policy.downloads == 2
        # 未声明键仍落缺省
        assert policy.sut_calls_total == 8

    def test_task_level_partial_override(self) -> None:
        task_set = _task_set({"nudges": 5, "downloads": 2})
        policy = resolve_interaction_policy(_task({"nudges": 1}), task_set)
        # 覆盖键取任务级
        assert policy.nudges == 1
        # 其余键保任务集级
        assert policy.downloads == 2
        assert policy.sut_calls_total == 8

    def test_invalid_subkey_falls_back_to_upper_layer(self) -> None:
        task_set = _task_set({"nudges": 5})
        # 非法键静默丢弃，合法键照常生效
        policy = resolve_interaction_policy(
            _task({"nudges": -1, "sut_calls_total": 0, "downloads": 3, "oops": 9}),
            task_set,
        )
        assert policy.nudges == 5  # 回退任务集级
        assert policy.sut_calls_total == 8  # 回退缺省
        assert policy.downloads == 3  # 合法键生效
        assert not hasattr(policy, "oops")

    def test_malformed_task_layer_ignored(self) -> None:
        """非 dict 形态（字符串/None）整体忽略，落缺省。"""
        task_set = _task_set({"nudges": 5})
        assert resolve_interaction_policy(_task("nudges=99"), task_set).nudges == 5
        assert resolve_interaction_policy(_task({"interaction_policy": None}), task_set).nudges == 5

    def test_combination_violation_falls_back_whole_task_layer(self) -> None:
        """组合违约（任务级 nudges 超出任务集 total-dispatch 余量）整层回退上层。"""
        task_set = _task_set({"sut_calls_total": 4})  # nudges 余量 = 4-1 = 3
        policy = resolve_interaction_policy(_task({"nudges": 5}), task_set)
        # 任务层整体回退：nudges 落任务集层级缺省 2（而非违约的 5）
        assert policy.nudges == 2
        assert policy.sut_calls_total == 4


class TestDeriveRecursionLimit:
    """保险丝推导：宽于语义预算，只兜图失控。"""

    def test_formula(self) -> None:
        # (sut_calls_total 8 + downloads 5 + state_polls 60 全额 + 固定余量 6) * 2 = 158
        assert derive_recursion_limit(InteractionPolicy()) == 158

    def test_polls_counted_in_full_not_discounted(self) -> None:
        """轮询全额计入（run 20260911_073626 回归）：合法轮询 21 次（42 步）不得熔断。

        1/10 折算时代保险丝 50 步，dispatch 2 + 轮询 42 + 下载 4 + 收尾 2 恰好
        触顶——语义预算只用 21/60；全额计入后同轨迹余量充足。
        """
        policy = InteractionPolicy(state_polls=21)
        limit = derive_recursion_limit(policy)
        # (8 + 5 + 21 + 6) * 2 = 80，严格宽于该轨迹的最大合法消耗 50 步
        assert limit == 80
        assert limit > 50

    def test_scales_with_declaration(self) -> None:
        policy = InteractionPolicy(sut_calls_total=20, downloads=10, state_polls=100)
        # (20 + 10 + 100 + 6) * 2 = 272
        assert derive_recursion_limit(policy) == 272

    def test_fuse_wider_than_declared_sut_calls(self) -> None:
        """保险丝恒宽于语义预算——正常消耗永不触顶。"""
        for total, downloads in ((4, 2), (8, 5), (30, 10)):
            policy = InteractionPolicy(sut_calls_total=total, downloads=downloads)
            assert derive_recursion_limit(policy) > total + downloads
