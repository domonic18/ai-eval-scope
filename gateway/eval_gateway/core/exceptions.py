"""异常体系 -- 继承 GatewayError（带 message + details），按模块分组。"""

from __future__ import annotations

from typing import Any


class GatewayError(Exception):
    """所有 gateway 异常的基类。"""

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class AuthError(GatewayError):
    """鉴权失败（签名错误 / Key 失效 / scope 不足）。"""


class JobNotFoundError(GatewayError):
    """任务不存在或不属于当前租户。"""

    def __init__(self, job_id: str) -> None:
        super().__init__(f"job not found: {job_id}")
        self.job_id = job_id


class InputInvalidError(GatewayError):
    """提交内容无法解析为有效评估输入。"""


class JobStateError(GatewayError):
    """任务状态不允许该操作（如取消已完成任务）。"""
