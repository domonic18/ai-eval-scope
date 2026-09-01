"""SUTRegistry 与 sut_config v2 模型（arch/03 §4.0.3）。

一份 sut_config.yaml 描述一个被测系统（顶层键 `sut:`），多系统即多份文件；
按 sut.name 索引聚合。注意与 arch/13 的 SUTConfig（benchmark 被测模型配置，
§5.3 Inferencer 路径）是两个不同概念——本模块为被测**系统**配置。

地址类字段支持 ``${VAR}`` / ``${VAR:-默认值}`` 环境变量展开（arch/17 开源
红线：内置包不得硬编码内部域名，真实端点由用户 env 提供，缺省回退占位域名）。
凭证值不走此通道——仍由 ``credential_ref`` 引用密钥区（06 §4.7）。
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from agent_eval.config.loader import ConfigLoader
from agent_eval.core.exceptions import SUTChannelError

# 支持的通道（v4.5 裁决：本期唯一排期 agent_protocol；其余预留）
CHANNEL_TYPES = ("agent_protocol", "generic_http", "browser")
EXEC_MODES = ("wait", "background", "stream")
STREAM_MODES = ("values", "messages", "updates", "custom")
AUTH_TYPES = ("none", "static_token", "api_login", "session_cookie")
# Agent Protocol 两种部署形态：runs（/runs/wait 族）| commands（/threads/{id}/commands + state）
PROTOCOL_FLAVORS = ("runs", "commands")

# ${VAR} / ${VAR:-默认值}（不支持嵌套占位；默认值内不含 '}'）
_ENV_REF = re.compile(r"\$\{([A-Z_][A-Z0-9_]*)(?::-(.*?))?\}")


def expand_env_refs(value: Any) -> Any:
    """递归展开 dict/list 中的 ``${VAR}`` / ``${VAR:-默认值}`` 占位（仅字符串字段）。

    env 已设 → 取 env 值；未设但有默认值 → 默认值；两者皆无 → SUTChannelError
    （报错优于保留原文——带着 ``${...}`` 去请求端点只会得到难懂的连接错误）。
    """
    if isinstance(value, dict):
        return {k: expand_env_refs(v) for k, v in value.items()}
    if isinstance(value, list):
        return [expand_env_refs(v) for v in value]

    def _repl(m: re.Match[str]) -> str:
        name, default = m.group(1), m.group(2)
        env = os.environ.get(name)
        if env:
            return env
        if default is not None:
            return default
        raise SUTChannelError(
            f"sut_config 引用了未定义的 env 变量 ${{{name}}}"
            f"（设置该变量，或改写为 ${{{name}:-默认值}}）"
        )

    return _ENV_REF.sub(_repl, value) if isinstance(value, str) else value


class AuthLoginConfig(BaseModel):
    """api_login / session_cookie 的登录接口模板。"""

    method: str = "POST"
    path: str = Field(
        description="登录接口路径（相对 base_url；跨域登录接口可填完整 http(s):// URL）"
    )
    body_template: str = Field(
        default='{"username": "{{ username }}", "password": "{{ password }}"}',
        description="登录请求体模板（Jinja2，username/password 从 env 凭证注入）",
    )


class AuthExtractConfig(BaseModel):
    """从登录响应提取会话凭证的规则。"""

    token_path: str | None = Field(default=None, description="token 的 JSON 点分路径")
    token_type: str = Field(
        default="Bearer", description='"Bearer" | "cookie" | "header:<HeaderName>"'
    )
    expires_in_path: str | None = Field(default=None, description="有效期秒数的 JSON 点分路径")


class AuthMountConfig(BaseModel):
    """业务请求的凭证挂载方式。"""

    header: str = Field(default="Authorization", description="Bearer 型挂载的请求头名")


class AuthConfig(BaseModel):
    """鉴权策略配置（arch/03 §4.0.2）。"""

    type: str = Field(
        default="none", description="none | static_token | api_login | session_cookie"
    )
    credential_ref: str | None = Field(default=None, description="凭证引用（env 注入键）")
    login: AuthLoginConfig | None = None
    extract: AuthExtractConfig | None = None
    mount: AuthMountConfig = Field(default_factory=AuthMountConfig)
    logout_on_finish: bool = False
    # 自动重登频次上限窗口（秒）：窗口内已自动重登过则拒绝再次重登（防风控锁号）
    relogin_window_s: float = Field(default=1800.0)

    @field_validator("type")
    @classmethod
    def _validate_type(cls, v: str) -> str:
        if v not in AUTH_TYPES:
            raise ValueError(f"auth.type 必须为 {AUTH_TYPES} 之一，得到: {v!r}")
        return v


class OutputPathsConfig(BaseModel):
    """Agent Protocol 产出物提取路径（取代 response_mapping）。"""

    files_field: str | None = Field(
        default=None, description="产出文件列表的点分路径，如 values.output_files"
    )
    text_field: str | None = Field(
        default=None, description="文本产出物的点分路径，如 values.content"
    )


class SUTSystemConfig(BaseModel):
    """单个被测系统配置（sut_config v2，顶层键 sut:）。"""

    name: str = Field(description="系统标识（SUTRegistry 索引键，全局唯一）")
    channel: str = Field(description="agent_protocol | generic_http（预留）| browser（预留）")
    base_url: str = Field(description="服务根地址")
    timeout: float = Field(default=120.0, description="默认超时（秒）")
    protocol_version: str | None = Field(
        default=None, description="Agent Protocol 实现版本（如 0.1.6）"
    )
    protocol_flavor: str = Field(
        default="runs",
        description="runs（POST /runs/wait 族）| commands（POST /threads/{id}/commands"
        " + GET state 轮询，官方 Streaming 端点形态）",
    )
    configurable: dict[str, Any] = Field(
        default_factory=dict,
        description='run 请求 config.configurable 缺省值（如 {"modelId": "19"}）',
    )
    agent_id: str | None = Field(default=None, description="缺省用服务默认 agent")
    exec_mode: str = Field(default="wait", description="wait | background | stream")
    stream_mode: str = Field(default="messages", description="exec_mode=stream 时的事件模式")
    auth: AuthConfig = Field(default_factory=AuthConfig)
    output_paths: OutputPathsConfig = Field(default_factory=OutputPathsConfig)
    on_completion: str | None = Field(default=None, description="如 delete（临时线程用完即删）")
    request_template: dict[str, Any] = Field(default_factory=dict, description="generic_http 预留")
    response_mapping: dict[str, str] = Field(default_factory=dict, description="generic_http 预留")

    model_config = ConfigDict(extra="allow")

    @field_validator("channel")
    @classmethod
    def _validate_channel(cls, v: str) -> str:
        if v not in CHANNEL_TYPES:
            raise ValueError(f"channel 必须为 {CHANNEL_TYPES} 之一，得到: {v!r}")
        return v

    @field_validator("exec_mode")
    @classmethod
    def _validate_exec_mode(cls, v: str) -> str:
        if v not in EXEC_MODES:
            raise ValueError(f"exec_mode 必须为 {EXEC_MODES} 之一，得到: {v!r}")
        return v

    @field_validator("protocol_flavor")
    @classmethod
    def _validate_protocol_flavor(cls, v: str) -> str:
        if v not in PROTOCOL_FLAVORS:
            raise ValueError(f"protocol_flavor 必须为 {PROTOCOL_FLAVORS} 之一，得到: {v!r}")
        return v

    @field_validator("stream_mode")
    @classmethod
    def _validate_stream_mode(cls, v: str) -> str:
        if v not in STREAM_MODES:
            raise ValueError(f"stream_mode 必须为 {STREAM_MODES} 之一，得到: {v!r}")
        return v


class SUTRegistry:
    """多系统注册表：加载 sut_configs（单文件或目录），按 sut.name 索引。"""

    def __init__(self, configs: dict[str, SUTSystemConfig]) -> None:
        self._configs = configs

    @classmethod
    def load(cls, path: Path | str) -> SUTRegistry:
        """加载单份 sut_config.yaml（顶层键 sut:；字符串字段先做 ${VAR} 展开）。"""
        data = ConfigLoader.load_yaml(path)
        sut_data = data.get("sut")
        if not isinstance(sut_data, dict):
            raise SUTChannelError(
                f"sut_config 缺少顶层 'sut:' 段: {path}", details={"path": str(path)}
            )
        config = SUTSystemConfig.model_validate(expand_env_refs(sut_data))
        return cls({config.name: config})

    @classmethod
    def load_dir(cls, directory: Path | str) -> SUTRegistry:
        """聚合加载目录下全部 *.yaml / *.yml（每份一个系统）。"""
        configs: dict[str, SUTSystemConfig] = {}
        for file in sorted(Path(directory).glob("*.y*ml")):
            registry = cls.load(file)
            configs.update(registry._configs)
        return cls(configs)

    def get(self, name: str) -> SUTSystemConfig:
        """按系统名取配置；不存在抛 SUTChannelError。"""
        if name not in self._configs:
            raise SUTChannelError(
                f"未注册的被测系统: {name!r}", details={"available": sorted(self._configs)}
            )
        return self._configs[name]

    @property
    def names(self) -> list[str]:
        """全部系统名。"""
        return sorted(self._configs)

    @property
    def default(self) -> SUTSystemConfig:
        """唯一系统（未指定名称时的缺省）；多系统时抛错要求显式指定。"""
        if len(self._configs) == 1:
            return next(iter(self._configs.values()))
        raise SUTChannelError(
            f"注册了 {len(self._configs)} 个系统，必须显式指定名称",
            details={"available": sorted(self._configs)},
        )

    def __len__(self) -> int:
        return len(self._configs)


__all__ = [
    "AuthConfig",
    "AuthExtractConfig",
    "AuthLoginConfig",
    "AuthMountConfig",
    "OutputPathsConfig",
    "SUTRegistry",
    "SUTSystemConfig",
    "expand_env_refs",
]
