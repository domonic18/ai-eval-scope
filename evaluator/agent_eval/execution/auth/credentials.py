"""CredentialStore — 凭证读取（arch/03 §4.0.1/§4.0.5；arch/06 §4.7 双通道）。

读取顺序：进程 env（云端注入）→ 本机密钥区文件（`~/.agent_eval/sut_credentials.json`，
`agent-eval secrets set` 录入）；sut_config 只存 credential_ref 引用。
凭证是**通用 KV**（arch/06 §4.7）：env 命名 `AGENT_EVAL_SUT__<CREDENTIAL_REF>__<FIELD>`，
字段名自由——所需字段由配置声明（见 required_credential_fields），代码不枚举字段集。
sut_config 中出现明文密码/token 属安全红线违规。
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from agent_eval.core.exceptions import SUTAuthError

ENV_PREFIX = "AGENT_EVAL_SUT__"


class CredentialStore:
    """被测系统凭证读取：env 优先、密钥区文件兜底（可注入便于测试）。"""

    def __init__(
        self,
        env: Mapping[str, str] | None = None,
        secrets_path: Path | None = None,
    ) -> None:
        self._env = os.environ if env is None else env
        self._secrets_path = secrets_path

    def _from_file(self, credential_ref: str, field: str) -> str | None:
        """密钥区文件查找（字段统一小写存储；ref 大小写不敏感；损坏时提示重置）。"""
        from agent_eval.execution.auth.secrets_store import load_secrets_file

        try:
            secrets = load_secrets_file(self._secrets_path)
        except SUTAuthError as e:
            raise SUTAuthError(f"{e}；如需重置可删除该文件后重新 secrets set") from e
        fields = secrets.get(credential_ref)
        if fields is None:  # 大小写不敏感兜底（sut_config 写 SASAN、录入 sasan 均可命中）
            fields = next(
                (v for k, v in secrets.items() if k.upper() == credential_ref.upper()), None
            )
        return (fields or {}).get(field.lower())

    def get(self, credential_ref: str, field: str) -> str | None:
        """读取凭证字段（env → 密钥区文件，ref 大小写不敏感）；未设置返回 None。"""
        value = self._env.get(f"{ENV_PREFIX}{credential_ref.upper()}__{field.upper()}")
        if value:
            return value
        return self._from_file(credential_ref, field)

    def require(self, credential_ref: str, field: str) -> str:
        """读取凭证字段；缺失抛 SUTAuthError（给出录入引导）。"""
        value = self.get(credential_ref, field)
        if not value:
            raise SUTAuthError(
                f"凭证未配置: {credential_ref}.{field.lower()}（sut_config 引用 "
                f"credential_ref={credential_ref!r}）；运行 "
                f"`agent-eval secrets set {credential_ref}.{field.lower()}` 录入，"
                f"或设置 env {ENV_PREFIX}{credential_ref}__{field.upper()}",
                details={"credential_ref": credential_ref, "field": field},
            )
        return value


def _template_fields(body_template: str) -> list[str]:
    """``body_template``（Jinja2）声明了哪些变量就要求哪些凭证字段——键名由配置声明。"""
    from jinja2 import Environment, meta

    return sorted(meta.find_undeclared_variables(Environment().parse(body_template)))


def required_credential_fields(sut: Any) -> list[str]:
    """sut_config 声明的所需凭证字段（大写）——**数据驱动，非代码枚举**（06 §4.7 通用 KV）。

    - api_login / session_cookie：``auth.login.body_template`` 的 Jinja2 变量即字段
      （模板写 ``{{ account }}`` 就要求 ``ref.account``；无 login 段由 AuthProvider 报配置错）；
    - static_token：协议约定字段 ``token``（arch/03 §4.0.2 语义）；
    - none：无。
    """
    auth = getattr(sut, "auth", None)
    auth_type = getattr(auth, "type", "none")
    if auth_type in ("api_login", "session_cookie"):
        body = getattr(getattr(auth, "login", None), "body_template", None) or ""
        return [f.upper() for f in _template_fields(body)]
    if auth_type == "static_token":
        return ["TOKEN"]
    return []


def preflight_sut_credentials(sut: Any) -> None:
    """执行前凭证预检：缺凭证立即失败（fail fast），不进 Agent 循环烧轮次。

    实测教训：凭证缺失时 SUTAuthError 只是工具返回值，ExecutionAgent 会换
    invoke_cli_sut/invoke_http_sut 反复试探，烧完 max_turns 才以「超过轮次限制」
    收场——真实原因被轮次错误掩盖。所需字段由 :func:`required_credential_fields`
    从 sut_config 数据推导，缺失即抛带 ``secrets set`` 引导的 SUTAuthError。
    """
    auth = getattr(sut, "auth", None)
    auth_type = getattr(auth, "type", "none")
    ref = getattr(auth, "credential_ref", None)
    fields = required_credential_fields(sut)
    if not fields:
        return
    if not ref:
        raise SUTAuthError(
            f"auth.type={auth_type!r} 需要 credential_ref（sut_config {sut.name} 的 auth 段）"
        )
    store = CredentialStore()
    for field in fields:  # require 缺失即抛（含录入引导）
        store.require(ref, field)
