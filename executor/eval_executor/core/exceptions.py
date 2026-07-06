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
