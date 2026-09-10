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

from jinja2 import Environment, TemplateError
from jinja2 import meta as jinja2_meta
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from agent_eval.config.loader import ConfigLoader
from agent_eval.core.exceptions import SUTChannelError

# 支持的通道（schema 合法值，含预留项）
CHANNEL_TYPES = ("agent_protocol", "generic_http", "browser")
# 本期已排期可执行通道（执行工厂/落盘门禁/执行域预检三处共用；排期变更只改这里，
# 与 CHANNEL_TYPES 互为补充）。v4.7 裁决：generic_http 落地（arch/03 §4.2），browser 仍预留
SCHEDULED_CHANNELS = ("agent_protocol", "generic_http")
# generic_http 请求模板允许的 HTTP 方法
HTTP_METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS")
# generic_http 响应提取的合法键（值=响应 JSON 的点分路径）
RESPONSE_MAPPING_KEYS = ("text", "files", "success")
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


def _normalize_http_method(v: str) -> str:
    upper = v.strip().upper()
    if upper not in HTTP_METHODS:
        raise ValueError(f"HTTP method 必须为 {HTTP_METHODS} 之一，得到: {v!r}")
    return upper


class RequestStepConfig(BaseModel):
    """链式请求模板的单步定义（arch/03 §4.2）。

    每步响应（JSON）进入渲染上下文，后续步以 ``{{ 步骤名.路径 }}`` 引用其值
    （值全程服务端流动，不经 LLM 转述）——jxb 类「建会话 → 发消息 → 查历史」
    的多步 API 靠它表达。
    """

    name: str = Field(description="步骤名（后续步以 {{ 步骤名.路径 }} 引用本步响应）")
    method: str = Field(description=f"HTTP 方法，{HTTP_METHODS} 之一")
    path: str = Field(description="请求路径（相对 base_url；跨域接口可填完整 http(s):// URL）")
    headers: dict[str, str] = Field(default_factory=dict, description="附加请求头（值支持模板）")
    body: Any = Field(
        default=None,
        description="请求体：dict 直发 JSON；str 须为合法 JSON 文本；字符串值支持模板",
    )

    @field_validator("name")
    @classmethod
    def _validate_name(cls, v: str) -> str:
        name = v.strip()
        # 步骤名进入 Jinja2 变量空间，须为合法标识符且不得遮蔽根变量
        if not re.fullmatch(r"\w+", name):
            raise ValueError(f"request_template.steps[].name 须为标识符（\\w+），得到: {v!r}")
        if name in ("input", "metadata"):
            raise ValueError(f"步骤名 {name!r} 与模板根变量冲突，请改名")
        return name

    @field_validator("method")
    @classmethod
    def _normalize_method(cls, v: str) -> str:
        return _normalize_http_method(v)


class RequestTemplateConfig(BaseModel):
    """generic_http 通道的请求模板（arch/03 §4.2）。

    body/headers 的字符串值支持 Jinja2 模板（变量空间 ``input``/``metadata``，
    由通道渲染）；凭证字段不得写在模板里——由 auth 会话自动挂载。
    多步 API 用 ``steps``（与单步 method/path 二选一），``response_mapping``
    作用于末步响应。
    """

    method: str | None = Field(
        default=None, description=f"单步形态的 HTTP 方法，{HTTP_METHODS} 之一"
    )
    path: str | None = Field(
        default=None,
        description="单步形态的请求路径（相对 base_url；跨域接口可填完整 http(s):// URL）",
    )
    headers: dict[str, str] = Field(default_factory=dict, description="附加请求头（值支持模板）")
    body: Any = Field(
        default=None,
        description="请求体：dict 直发 JSON；str 须为合法 JSON 文本；字符串值支持模板",
    )
    steps: list[RequestStepConfig] = Field(
        default_factory=list,
        description="链式多步请求（与单步 method/path 二选一）：逐步执行，"
        "后续步可 {{ 前序步骤名.路径 }} 引用其响应；response_mapping 作用于末步",
    )

    @field_validator("method")
    @classmethod
    def _normalize_method(cls, v: str | None) -> str | None:
        return None if v is None else _normalize_http_method(v)

    @model_validator(mode="after")
    def _check_shape(self) -> RequestTemplateConfig:
        if self.steps:
            if self.path is not None:
                raise ValueError("request_template 的 steps 与单步 method/path 不可混用——二选一")
        elif self.path is None:
            raise ValueError("request_template 需要单步（method/path）或 steps 列表（二选一）")
        if len({s.name for s in self.steps}) != len(self.steps):
            raise ValueError("request_template.steps 存在重复步骤名")
        return self


class SUTSystemConfig(BaseModel):
    """单个被测系统配置（sut_config v2，顶层键 sut:）。"""

    name: str = Field(description="系统标识（SUTRegistry 索引键，全局唯一）")
    channel: str = Field(description="agent_protocol | generic_http | browser（预留）")
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
    artifact_hosts: list[str] = Field(
        default_factory=list,
        description=(
            "产物下载额外放行域（download_sut_file 白名单 = base_url 域 ∪ 此列表；"
            "仅加产物实际所在的域，缺省只允许 SUT 同域下载）"
        ),
    )
    on_completion: str | None = Field(default=None, description="如 delete（临时线程用完即删）")
    request_template: RequestTemplateConfig | None = Field(
        default=None, description="generic_http 请求模板（channel=generic_http 必填）"
    )
    response_mapping: dict[str, str] = Field(
        default_factory=dict,
        description="generic_http 响应提取：键 text/files/success，值为响应 JSON 的点分路径",
    )

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


def resolve_login_url(base_url: str, login_path: str) -> str:
    """解析登录接口的最终请求 URL：绝对 path 直用，否则拼 sut.base_url。

    执行器登录（``provider._login_by_api``）与创建侧落盘对账门禁共用此函数——
    「配置实际会打到哪个 URL」只有一处真相。实测教训：Agent 把已实测的跨域登录
    接口拆成相对 path + 自造的 ``login.base_url`` 字段（执行器无此字段，静默
    丢弃）后拼回页面域，登录 404。
    """
    if login_path.startswith(("http://", "https://")):
        return login_path
    return f"{base_url.rstrip('/')}/{login_path.lstrip('/')}"


def _unknown_key_errors(data: dict[str, Any], model: type[BaseModel], path: str) -> list[str]:
    """未知键 = 执行器将静默丢弃的配置——以模型字段为白名单显式打回。

    白名单即 ``model_fields`` 本身，不引入第二份会漂移的字段清单。
    """
    hint = ""
    if path == "sut.auth.login":
        hint = "（跨域登录接口把完整 http(s):// URL 写进 path——没有 base_url 字段）"
    known = set(model.model_fields)
    return [
        f"{path} 含未知字段 {k!r}，执行器会静默丢弃{hint}；合法字段: {sorted(known)}"
        for k in sorted(set(data) - known)
    ]


def _collect_template_strings(value: Any) -> list[str]:
    """递归收集模板字符串叶子（path / headers 值 / body 树内字符串）。"""
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for item in value.values() for s in _collect_template_strings(item)]
    if isinstance(value, list):
        return [s for item in value for s in _collect_template_strings(item)]
    return []


def _template_variables(shape: dict[str, Any]) -> set[str]:
    """提取单个请求步模板的未声明变量根名集（语法错误叶子跳过——执行侧
    health_check 专项报告语法，此处只做变量可解析性审计）。"""
    strings = _collect_template_strings(shape.get("path"))
    strings += _collect_template_strings(shape.get("headers") or {})
    strings += _collect_template_strings(shape.get("body"))
    variables: set[str] = set()
    for source in strings:
        try:
            variables |= jinja2_meta.find_undeclared_variables(Environment().parse(source))
        except TemplateError:
            continue
    return variables


def _template_audit_errors(rt: dict[str, Any]) -> list[str]:
    """generic_http 模板变量审计：变量引用必须可解析，且必须消费 {{ input }}。

    实测事故（jxb，v4.8）：request_template 连 {{ input }} 都没写——16 条
    测试指令从未发给被测系统，每次调用只是「创建会话」，status=success 假成功
    烧穿执行轮次。凡可机械判定的配置变形在落盘前打回，不留给运行时让执行
    Agent 猜。
    """
    errors: list[str] = []
    raw_steps = rt.get("steps")
    step_shapes: list[tuple[str | None, dict[str, Any]]] = (
        [(str(s.get("name") or f"#{i}"), s) for i, s in enumerate(raw_steps) if isinstance(s, dict)]
        if isinstance(raw_steps, list)
        else [(None, rt)]
    )
    declared: set[str] = set()
    all_variables: set[str] = set()
    for step_name, shape in step_shapes:
        variables = _template_variables(shape)
        all_variables |= variables
        for bad in sorted(variables - {"input", "metadata", *declared}):
            where = f"（步骤 {step_name}）" if step_name else ""
            declared_list = f"、前序步骤名 {sorted(declared)}" if declared else ""
            errors.append(
                f"sut.request_template{where} 引用未定义变量 {bad!r}"
                f"（合法变量: input、metadata{declared_list}）"
            )
        if step_name:
            declared.add(step_name)
    if "input" not in all_variables:
        errors.append(
            "sut.request_template 未引用 {{ input }}——测试指令不会发送给被测系统"
            "（body/path 须含 {{ input }} 或 {{ input.字段 }}）"
        )
    return errors


def _brief_validation_errors(err: ValidationError) -> str:
    parts = [
        f"{'.'.join(str(loc) for loc in item['loc']) or 'sut'}: {item['msg']}"
        for item in err.errors()[:5]
    ]
    more = f"（等共 {err.error_count()} 处）" if err.error_count() > 5 else ""
    return "; ".join(parts) + more


def validate_sut_config_document(data: Any) -> list[str]:
    """校验单份 sut_config 文档（包校验层入口）：schema 必填/枚举 + 未知键拒绝。

    执行器模型 ``extra="allow"``（运行时前向兼容），但未知键会被**静默丢弃**——
    Agent 落盘时发明的字段不报错、不生效，配置与意图悄然背离（实测：登录 404）。
    包校验层负责把「静默丢弃」变成「显式打回」；``${VAR}`` 展开语义与执行器
    加载（``SUTRegistry.load``）完全一致。
    """
    if not isinstance(data, dict) or not isinstance(data.get("sut"), dict):
        return ["sut_config 缺少顶层 'sut:' 段"]
    sut = data["sut"]
    errors = _unknown_key_errors(sut, SUTSystemConfig, "sut")
    for section, model in (
        ("auth", AuthConfig),
        ("output_paths", OutputPathsConfig),
        ("request_template", RequestTemplateConfig),
    ):
        if isinstance(sut.get(section), dict):
            errors += _unknown_key_errors(sut[section], model, f"sut.{section}")
    auth = sut.get("auth")
    if isinstance(auth, dict):
        for name, auth_model in (
            ("login", AuthLoginConfig),
            ("extract", AuthExtractConfig),
            ("mount", AuthMountConfig),
        ):
            if isinstance(auth.get(name), dict):
                errors += _unknown_key_errors(auth[name], auth_model, f"sut.auth.{name}")
    if str(sut.get("channel", "")).lower() == "generic_http":
        # 通道必需段前置报缺（模型层 request_template 可空——agent_protocol 包不该被迫填它）
        if not isinstance(sut.get("request_template"), dict):
            errors.append(
                "channel=generic_http 需配置 request_template（单步 method/path 或 steps 链"
                "——多步 API 用 steps，后续步以 {{ 前序步骤名.路径 }} 引用其响应；"
                "body 与 headers 值支持 Jinja2 模板，变量空间 input/metadata）"
            )
        else:
            errors += _template_audit_errors(sut["request_template"])
        bad_keys = sorted(set(sut.get("response_mapping") or {}) - set(RESPONSE_MAPPING_KEYS))
        if bad_keys:
            errors.append(
                f"sut.response_mapping 含未知键 {bad_keys}（合法键: "
                f"{list(RESPONSE_MAPPING_KEYS)}——值为响应 JSON 的点分路径）"
            )
    try:
        SUTSystemConfig.model_validate(expand_env_refs(sut))
    except ValidationError as e:
        errors.append(f"sut 段校验失败: {_brief_validation_errors(e)}")
    except SUTChannelError as e:
        errors.append(str(e))
    return errors


class SUTRegistry:
    """多系统注册表：加载 sut_configs（单文件或目录），按 sut.name 索引。

    文件名 stem 作为**取用容错键**（实测两次：向导/CLI 以文件名列出并选择 SUT，
    Agent 生成包的 ``sut.name`` 却与文件名漂移——get() 在注册名未命中时按 stem
    兜底。机械容错而非门禁拦卡：一致性问题不拦 Agent（v3.12 评审裁决），执行侧
    让 stem 与 name 等价可解析）。
    """

    def __init__(
        self,
        configs: dict[str, SUTSystemConfig],
        stems: dict[str, str] | None = None,
    ) -> None:
        self._configs = configs
        self._stems = stems or {}  # 文件名 stem → 注册名（stem 与 name 漂移时的容错索引）

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
        return cls({config.name: config}, {Path(path).stem: config.name})

    @classmethod
    def load_dir(cls, directory: Path | str) -> SUTRegistry:
        """聚合加载目录下全部 *.yaml / *.yml（每份一个系统）。"""
        configs: dict[str, SUTSystemConfig] = {}
        stems: dict[str, str] = {}
        for file in sorted(Path(directory).glob("*.y*ml")):
            registry = cls.load(file)
            configs.update(registry._configs)
            stems.update(registry._stems)
        return cls(configs, stems)

    def get(self, name: str) -> SUTSystemConfig:
        """按系统名取配置；注册名未命中时按文件名 stem 兜底；都不存在抛 SUTChannelError。"""
        if name not in self._configs:
            registered = self._stems.get(name)
            if registered is not None:
                return self._configs[registered]
            raise SUTChannelError(
                f"未注册的被测系统: {name!r}",
                details={"available": sorted(self._configs), "file_names": sorted(self._stems)},
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
    "RequestTemplateConfig",
    "SCHEDULED_CHANNELS",
    "SUTRegistry",
    "SUTSystemConfig",
    "expand_env_refs",
]
