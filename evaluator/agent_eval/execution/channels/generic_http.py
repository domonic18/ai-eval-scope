"""GenericHttpChannel —— generic_http 通道（arch/03 §4.2，v4.7 排期落地）。

面向未实现 Agent Protocol 的 HTTP 服务：sut_config 的 ``request_template``
（Jinja2 模板，变量空间 input/metadata；多步 API 用 steps 链，后续步以
``{{ 步骤名.路径 }}`` 引用前序步响应）定义请求形态，``response_mapping``
（点分路径）从**末步**响应 JSON 提取回答文本/产物文件/成功标志。请求经基座
``request()`` 发出——鉴权挂载、401/403 自动重登、共享 client 全部复用。

与 agent_protocol 通道的差异：无线程/多轮语义（多轮任务由执行 Agent 逐轮
调用工具，每轮独立请求），exec_mode/stream 不适用。
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
from jinja2 import Environment, StrictUndefined
from jinja2.exceptions import TemplateError

from agent_eval.core.exceptions import SUTChannelError, ToolExecutionError
from agent_eval.execution.channels.base import SUTChannel
from agent_eval.execution.registry import RequestTemplateConfig, SUTSystemConfig
from agent_eval.execution.utils import extract_by_path

# 失败 error.message 的截断上限（上下文经济性，非业务阈值）
_ERROR_MAX_CHARS = 4000
# 提取失败给执行 Agent 的响应体摘录长度（自我修正映射路径的最小证据）
_EXCERPT_CHARS = 500
# SSE 流式响应的 content-type 标记（jxb 类消息接口回 text/event-stream）
_SSE_CONTENT_TYPE = "text/event-stream"


def _walk_leaves(prefix: str, value: Any, leaves: list[tuple[str, str]]) -> None:
    """递归收集模板字符串叶子（health_check 语法自检用）。"""
    if isinstance(value, str):
        leaves.append((prefix, value))
    elif isinstance(value, dict):
        for key, item in value.items():
            _walk_leaves(f"{prefix}.{key}", item, leaves)
    elif isinstance(value, list):
        for i, item in enumerate(value):
            _walk_leaves(f"{prefix}.{i}", item, leaves)


def _template_leaves(template: RequestTemplateConfig) -> list[tuple[str, str]]:
    """全部模板叶子：单步（path/headers/body）或 steps 链逐步收集。"""
    leaves: list[tuple[str, str]] = []
    if template.steps:
        for i, step in enumerate(template.steps):
            leaves.append((f"steps[{i}].path", step.path))
            for key, value in step.headers.items():
                _walk_leaves(f"steps[{i}].headers.{key}", value, leaves)
            _walk_leaves(f"steps[{i}].body", step.body, leaves)
    else:
        if template.path:
            leaves.append(("path", template.path))
        for key, value in template.headers.items():
            _walk_leaves(f"headers.{key}", value, leaves)
        _walk_leaves("body", template.body, leaves)
    return leaves


def _parse_sse_events(text: str) -> list[Any]:
    """机械解析 SSE ``data:`` 帧为事件列表（逐帧 JSON 解析，失败保原文）。

    mapping 按 ``events.N.字段`` 提取（如末帧 ``events.-1.content``）；
    ``data: [DONE]`` 哨兵终止。未配置 mapping 时整段原文即回答，不走此解析。
    """
    events: list[Any] = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        raw = line[len("data:") :].strip()
        if raw == "[DONE]":
            break
        try:
            events.append(json.loads(raw))
        except ValueError:
            events.append(raw)
    return events


class GenericHttpChannel(SUTChannel):
    """generic_http 通道：模板化 HTTP 请求（单步或 steps 链）+ response_mapping 提取。"""

    channel_type = "generic_http"

    def __init__(
        self,
        sut: SUTSystemConfig,
        *,
        auth_provider: Any = None,
        http_client_factory: Callable[[], httpx.AsyncClient] | None = None,
    ) -> None:
        super().__init__(sut, auth_provider=auth_provider, http_client_factory=http_client_factory)
        if sut.request_template is None:
            raise SUTChannelError(
                f"SUT {sut.name} channel=generic_http 但未配置 request_template"
                "（单步 method/path 或 steps 链，可选 headers/body）"
            )

    def _render(self, source: str, context: dict[str, Any]) -> str:
        """StrictUndefined 渲染单值——拼错变量名报错而非静默空串。

        静默空串会把「模板写错」伪装成「服务端返回空」，排查方向全错。
        """
        try:
            return Environment(undefined=StrictUndefined).from_string(source).render(**context)
        except TemplateError as e:
            raise SUTChannelError(
                f"request_template 渲染失败: {e}（变量空间仅 input/metadata/前序步骤名——"
                "字符串模板形如 {{ input }}、{{ metadata.字段 }} 或 {{ 步骤名.路径 }}）"
            ) from e

    def _render_leaf(self, value: Any, context: dict[str, Any]) -> Any:
        if isinstance(value, str):
            return self._render(value, context)
        if isinstance(value, dict):
            return {k: self._render_leaf(v, context) for k, v in value.items()}
        if isinstance(value, list):
            return [self._render_leaf(v, context) for v in value]
        return value

    def _rendered_body(self, body: Any, context: dict[str, Any]) -> dict[str, Any] | None:
        rendered = self._render_leaf(body, context)
        if rendered is None:
            return None
        if isinstance(rendered, dict):
            return rendered
        if isinstance(rendered, str):
            try:
                loaded = json.loads(rendered)
            except json.JSONDecodeError as e:
                raise SUTChannelError(
                    f"request_template.body 渲染后不是合法 JSON: {e}——str 形态须为 JSON 文本，"
                    "推荐直接写 dict 形态（免手工转义）"
                ) from e
            if not isinstance(loaded, dict):
                raise SUTChannelError(
                    f"request_template.body 渲染后须为 JSON 对象，得到: {type(loaded).__name__}"
                )
            return loaded
        raise SUTChannelError(f"request_template.body 类型不支持: {type(rendered).__name__}")

    async def _send(
        self,
        method: str,
        path: str,
        headers: dict[str, str],
        body: Any,
        context: dict[str, Any],
    ) -> httpx.Response:
        """渲染单步模板并发出请求（鉴权/重登/共享 client 复用基座）。"""
        return await self.request(
            method,
            str(self._render_leaf(path, context)),
            json_body=self._rendered_body(body, context),
            headers={k: str(self._render_leaf(v, context)) for k, v in headers.items()},
        )

    def _capture(self, response: httpx.Response) -> dict[str, Any]:
        """步骤响应进入后续步渲染上下文：JSON 原样；非 JSON（SSE 等）→ text 包装。"""
        try:
            payload = response.json()
        except ValueError:
            return {"text": response.text}
        if isinstance(payload, dict):
            return payload
        return {"value": payload}

    def _http_failed(self, prefix: str, response: httpx.Response) -> dict[str, Any]:
        return {
            "status": "failed",
            "run": {},
            "text": "",
            "output": {"text": "", "files": []},
            "http_status": response.status_code,
            "error": {
                "code": f"http_{response.status_code}",
                "message": f"{prefix}{response.text[:_ERROR_MAX_CHARS]}",
            },
        }

    async def run(
        self,
        input: Any,
        *,
        exec_mode: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """渲染 request_template → 逐步（或单步）发请求 → response_mapping 提取末步。

        返回契约与 AgentProtocolChannel.run 同构（消费方 last_run 只认
        status/run/text/output）：steps 链中任一步 ≥400 即整体 failed（错误
        带步骤名）；失败带 error{code,message}。
        """
        del exec_mode  # 无流式/后台语义（无线程模型），参数保留仅为签名同构
        template = self.sut.request_template
        assert template is not None  # 构造期已守卫
        context: dict[str, Any] = {"input": input, "metadata": metadata or {}}
        response: httpx.Response | None = None
        if template.steps:
            for step in template.steps:
                response = await self._send(
                    step.method, step.path, step.headers, step.body, context
                )
                if response.status_code >= 400:
                    return self._http_failed(f"步骤 {step.name}: ", response)
                context[step.name] = self._capture(response)
        else:
            response = await self._send(
                template.method or "POST",
                template.path or "",
                template.headers,
                template.body,
                context,
            )
            if response.status_code >= 400:
                return self._http_failed("", response)
        assert response is not None  # steps 非空由 RequestTemplateConfig 模型校验保证
        return self._extract(response)

    def _parse_payload(self, response: httpx.Response) -> Any:
        """末步响应解析：SSE → events 包装（机械解析 data: 帧）；JSON → 原样。"""
        if _SSE_CONTENT_TYPE in response.headers.get("content-type", "").lower():
            return {"events": _parse_sse_events(response.text)}
        try:
            return response.json()
        except ValueError as e:
            raise SUTChannelError(
                f"SUT 响应不是合法 JSON，无法按 response_mapping 提取: {e}"
                "（纯文本响应请把 response_mapping 留空，整个响应体即回答文本）"
            ) from e

    def _extract(self, response: httpx.Response) -> dict[str, Any]:
        mapping = self.sut.response_mapping or {}
        # JSON 惰性解析：未配置 mapping 的纯文本 API（body 即回答）不该被解析拦住
        payload: Any = None
        if mapping:
            payload = self._parse_payload(response)
        text, text_error = self._extract_text(payload, response, mapping)
        status = "success"
        error: dict[str, str] | None = text_error
        if error:
            status = "failed"
        if "files" in mapping:
            files = self._extract_required(payload, mapping["files"], "files")
            if not isinstance(files, list):
                raise SUTChannelError(
                    f"response_mapping.files 提取结果须为列表，得到: {type(files).__name__}"
                )
        else:
            files = []
        if "success" in mapping:
            ok = self._extract_required(payload, mapping["success"], "success")
            if not ok:
                status = "failed"
                error = {
                    "code": "success_false",
                    "message": f"response_mapping.success 路径取值为 falsy: {ok!r}",
                }
        result: dict[str, Any] = {
            "status": status,
            "run": {},
            "text": text,
            "output": {"text": text, "files": files},
            "http_status": response.status_code,
        }
        if error:
            result["error"] = error
        return result

    def _extract_text(
        self, payload: Any, response: httpx.Response, mapping: dict[str, str]
    ) -> tuple[str, dict[str, str] | None]:
        """text 提取：未配置 → 整个响应体（纯文本 API 的合法兜底）；
        已配置但路径未命中/取 null → failed（不再静默兜底整包——假成功红线）。

        实测事故（jxb，v4.8）：路径 ``data.messages[-1].content`` 方括号形式
        不被解析、未命中被兜底成「创建成功」整包 JSON，status=success 假成功。
        """
        if "text" not in mapping:
            return response.text, None
        try:
            value = extract_by_path(payload, mapping["text"])
        except ToolExecutionError as e:
            return "", {
                "code": "text_path_miss",
                "message": (
                    f"response_mapping.text 路径无法解析: {e}——核对映射路径"
                    "（列表末元素用 -1 或 [-1]，SSE 流式响应按 events.N.字段提取）；"
                    "需整响应体作回答请留空 response_mapping；"
                    f"响应体摘录: {response.text[:_EXCERPT_CHARS]}"
                ),
            }
        if value is None:
            return "", {
                "code": "text_path_miss",
                "message": (
                    f"response_mapping.text 路径 {mapping['text']!r} 取值为 null"
                    f"——响应体摘录: {response.text[:_EXCERPT_CHARS]}"
                ),
            }
        if isinstance(value, str):
            return value, None
        return json.dumps(value, ensure_ascii=False), None

    def _extract_required(self, payload: Any, path: str, name: str) -> Any:
        """files/success 为显式声明路径——未命中属配置变形，报错而非兜底。"""
        try:
            return extract_by_path(payload, path)
        except ToolExecutionError as e:
            raise SUTChannelError(f"response_mapping.{name} 路径无法解析: {e}") from e

    async def health_check(self) -> dict[str, Any]:
        """接入自检：request_template 模板语法静态校验（零网络请求）。

        变量存在性与端点可达性无法离线判定——变量缺失在 run 时由
        StrictUndefined 报错（落盘前已由 validate_sut_config_document 变量
        审计拦截），端点问题由执行 Agent 据工具结果自主处置。
        """
        template = self.sut.request_template
        if template is None:
            raise SUTChannelError(
                f"SUT {self.sut.name} channel=generic_http 但未配置 request_template"
            )
        env = Environment(undefined=StrictUndefined)
        for field, source in _template_leaves(template):
            try:
                env.parse(source)
            except TemplateError as e:
                raise SUTChannelError(f"request_template.{field} 模板语法错误: {e}") from e
        return {"status": "ok", "channel": self.channel_type, "sut": self.sut.name}


__all__ = ["GenericHttpChannel"]
