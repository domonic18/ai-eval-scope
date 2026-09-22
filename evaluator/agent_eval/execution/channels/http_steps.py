"""generic_http 链执行原语（M1 会话续接 + M2 异步轮询）。

从 GenericHttpChannel 下沉的两块机制（保持通道文件精简）：

StepSession —— once 步响应的跨调用缓存（会话续接）：键 session_key（执行
框架按任务注入，跨任务不串），值「步骤名 → 响应 capture」（只存 once 步）；
LRU 淘汰最久未用会话，淘汰即丢——由 run_steps 的自愈路径整链重建兜底。

run_steps —— steps 链执行循环：once 步缓存命中跳过请求（会话首轮之外不再
重建会话）；poll 步 do-while 反复执行直到 until 渲染为真或超时；非 once 步
404 且会话缓存非空时自动清缓存整链重建一次（服务端会话过期的自愈形态）。

渲染/发送/提取复用通道既有原语（_send/_capture/_extract/_render/_http_failed），
本模块不复制实现——以 channel 实例为参数直接调用（同包友元模块）。
"""

from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

import httpx

from agent_eval.core.exceptions import SUTChannelError
from agent_eval.execution.registry import RequestStepConfig, RequestTemplateConfig

if TYPE_CHECKING:
    from agent_eval.execution.channels.generic_http import GenericHttpChannel

# 测试注入点：monkeypatch 本符号即可推进轮询，不等真实 interval
_sleep: Callable[[float], Awaitable[None]] = asyncio.sleep

# until 渲染结果的真值集合（strip+lower 后比对——"True"/" YES " 亦判真）
_UNTIL_TRUTHY = {"true", "1", "yes"}

# poll_timeout 错误里的响应体摘录长度（自我修正的最小证据）
_EXCERPT_CHARS = 500

# 会话缓存 LRU 上限（淘汰即丢，自愈整链重建兜底）
_MAX_SESSIONS = 32

# 会话键缺省（工具面未注入 current_session_key 时的兜底——单任务直连场景）
_DEFAULT_SESSION_KEY = "default"


def _walk_leaves(prefix: str, value: Any, leaves: list[tuple[str, str]]) -> None:
    """递归收集模板字符串叶子。"""
    if isinstance(value, str):
        leaves.append((prefix, value))
    elif isinstance(value, dict):
        for key, item in value.items():
            _walk_leaves(f"{prefix}.{key}", item, leaves)
    elif isinstance(value, list):
        for i, item in enumerate(value):
            _walk_leaves(f"{prefix}.{i}", item, leaves)


def template_leaves(template: RequestTemplateConfig) -> list[tuple[str, str]]:
    """全部模板叶子：单步（path/headers/body）或 steps 链逐步收集。

    health_check 语法自检与变量审计共用的模板结构遍历。
    """
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


class StepSession:
    """once 步响应的会话缓存：session_key → {步骤名 → capture}，LRU 上限淘汰。"""

    def __init__(self, max_sessions: int = _MAX_SESSIONS) -> None:
        self._max = max_sessions
        self._store: OrderedDict[str, dict[str, dict[str, Any]]] = OrderedDict()

    def cache_for(self, session_key: str) -> dict[str, dict[str, Any]]:
        """取会话缓存（LRU 触碰：命中移尾部；未命中新建并淘汰超限最旧项）。"""
        cache = self._store.get(session_key)
        if cache is None:
            cache = {}
            self._store[session_key] = cache
            while len(self._store) > self._max:
                self._store.popitem(last=False)
        else:
            self._store.move_to_end(session_key)
        return cache

    def discard(self, session_key: str) -> None:
        """丢弃单会话缓存（new_session 显式重建 / 404 自愈）。"""
        self._store.pop(session_key, None)

    def clear(self) -> None:
        """全清（aclose 时调用——会话属于单次评测运行，不跨运行存活）。"""
        self._store.clear()

    def __len__(self) -> int:
        return len(self._store)


async def run_steps(
    channel: GenericHttpChannel,
    template: RequestTemplateConfig,
    input: Any,
    metadata: dict[str, Any],
    session: StepSession,
    *,
    session_key: str = _DEFAULT_SESSION_KEY,
    new_session: bool = False,
) -> dict[str, Any]:
    """执行 steps 链（once 跳过 / poll 轮询 / 404 自愈），返回 run() 同构结果。

    自愈仅触发一次且仅当首轮会话缓存非空：非 once 步 404 = 服务端会话过期
    的典型形态，清缓存整链重建；重建成功结果标注 ``session_rebuilt: true``，
    重建仍 404 判 failed 且错误带两轮证据（业务性 404 不无限重试）。
    """
    if new_session:
        session.discard(session_key)
    result, healable = await _run_chain(channel, template, input, metadata, session, session_key)
    if not healable:
        return result
    first_error = result.get("error", {}).get("message", "")
    session.discard(session_key)  # 旧会话缓存视为过期，整链重建
    result, _ = await _run_chain(channel, template, input, metadata, session, session_key)
    result["session_rebuilt"] = True
    if result.get("status") == "failed" and result.get("http_status") == 404:
        result["error"]["message"] += (
            f"（会话自愈已整链重建一次仍 404——首轮失败证据: {first_error[:200]}）"
        )
    return result


async def _run_chain(
    channel: GenericHttpChannel,
    template: RequestTemplateConfig,
    input: Any,
    metadata: dict[str, Any],
    session: StepSession,
    session_key: str,
) -> tuple[dict[str, Any], bool]:
    """单轮链执行，返回 (结果, 可自愈)。

    可自愈 = 非 once 步命中 404 且本轮开始时会话缓存非空（once 步 404 是
    建会话本身失败，缓存必为空，不属会话过期形态）。
    """
    cache = session.cache_for(session_key)
    had_cache = bool(cache)
    # once 缓存进渲染上下文——续轮里 {{ create.data.id }} 写法与单次链内一致
    context: dict[str, Any] = {"input": input, "metadata": metadata, **cache}
    response: httpx.Response | None = None
    for step in template.steps:
        if step.name in cache:
            continue  # once 步缓存命中——不重复建会话
        if step.poll is not None:
            response = await _poll_step(channel, step, context)
        else:
            response = await channel._send(step.method, step.path, step.headers, step.body, context)
            if response.status_code >= 400:
                healable = had_cache and response.status_code == 404 and not step.once
                return channel._http_failed(f"步骤 {step.name}: ", response), healable
        capture = channel._capture(response)
        context[step.name] = capture
        if step.once:
            cache[step.name] = capture  # 仅成功响应入会话缓存
    # 末步 not-once 由 RequestTemplateConfig 模型门保证——必有一次请求可提取
    assert response is not None
    return channel._extract(response), False


async def _poll_step(
    channel: GenericHttpChannel, step: RequestStepConfig, context: dict[str, Any]
) -> httpx.Response:
    """poll 步 do-while：先发请求再判终态，超时 failed 带最后响应证据。

    本步响应 capture 进 context（自引用可见）；轮询中 ≥400 不立即失败
    （受理后短暂不一致是常态），续轮直至终态或超时；
    until 渲染错误经 StrictUndefined 抛 SUTChannelError——fail-loud。
    """
    poll = step.poll
    assert poll is not None  # 调用方已判
    deadline = time.monotonic() + poll.timeout_s
    attempts = 0
    last_excerpt = ""
    while True:
        attempts += 1
        response = await channel._send(step.method, step.path, step.headers, step.body, context)
        context[step.name] = channel._capture(response)
        if response.status_code < 400:
            rendered = channel._render(poll.until, context)
            if rendered.strip().lower() in _UNTIL_TRUTHY:
                return response
            last_excerpt = response.text[:_EXCERPT_CHARS]
        else:
            last_excerpt = f"HTTP {response.status_code}: {response.text[:_EXCERPT_CHARS]}"
        if time.monotonic() >= deadline:
            raise SUTChannelError(
                f"poll 步骤 {step.name} 轮询超时（timeout_s={poll.timeout_s:g}s，"
                f"尝试 {attempts} 次）——最后响应摘录: {last_excerpt}"
            )
        await _sleep(poll.interval_s)


__all__ = ["StepSession", "run_steps", "template_leaves"]
