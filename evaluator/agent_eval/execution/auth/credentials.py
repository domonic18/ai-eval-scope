"""CredentialStore — 凭证读取（arch/03 §4.0.1/§4.0.5）。

凭证仅从环境变量注入，sut_config 只存 credential_ref 引用；
env 命名约定：AGENT_EVAL_SUT__<CREDENTIAL_REF>__{USERNAME|PASSWORD|TOKEN}。
sut_config 中出现明文密码/token 属安全红线违规。
"""

from __future__ import annotations

import os
from collections.abc import Mapping

from agent_eval.core.exceptions import SUTAuthError

ENV_PREFIX = "AGENT_EVAL_SUT__"

# 支持的凭证字段（大写形式）
FIELDS = ("USERNAME", "PASSWORD", "TOKEN")


class CredentialStore:
    """从环境变量读取被测系统凭证（可注入自定义 env 便于测试）。"""

    def __init__(self, env: Mapping[str, str] | None = None) -> None:
        self._env = os.environ if env is None else env

    def get(self, credential_ref: str, field: str) -> str | None:
        """读取凭证字段；未设置返回 None。"""
        return self._env.get(f"{ENV_PREFIX}{credential_ref}__{field.upper()}")

    def require(self, credential_ref: str, field: str) -> str:
        """读取凭证字段；缺失抛 SUTAuthError（给出 env 变量名提示）。"""
        value = self.get(credential_ref, field)
        if not value:
            var_name = f"{ENV_PREFIX}{credential_ref}__{field.upper()}"
            raise SUTAuthError(
                f"凭证未配置: {var_name}（sut_config 引用 credential_ref={credential_ref!r}）",
                details={"env_var": var_name, "credential_ref": credential_ref},
            )
        return value
