"""异常体系 -- 继承 ExecutorError（带 message + details），按模块分组。"""

from __future__ import annotations

from typing import Any


class ExecutorError(Exception):
    """所有 executor 异常的基类。"""

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class AuthError(ExecutorError):
    """鉴权失败（token 解密失败 / Key 失效）。"""


class JobNotFoundError(ExecutorError):
    """任务不存在。"""

    def __init__(self, job_id: str) -> None:
        super().__init__(f"job not found: {job_id}")
        self.job_id = job_id


class RuleSetNotFoundError(ExecutorError):
    """规则集 id 未注册。

    未知 id 不再静默回退默认规则集（曾导致跑错规则集的正确性隐患），
    一律抛本异常，由上层 ``run_job`` 捕获后 mark_failed。
    """

    def __init__(self, rule_set_id: str) -> None:
        super().__init__(f"rule set not found: {rule_set_id}")
        self.rule_set_id = rule_set_id


class LegacyJobRejectedError(ExecutorError):
    """历史 job（仅 rule_set_id、无 package_ref）被拒绝。

    S2-C/D：executor 不再用内置 _BUILTIN 映射，必须由 job.package_ref 指定场景包。
    缺失 package_ref 的历史 job 一律拒绝，避免跑错规则集。
    """

    def __init__(self, job_id: str) -> None:
        super().__init__(
            f"legacy job rejected (no package_ref): {job_id}；请用 package_ref 重新提交"
        )
        self.job_id = job_id
