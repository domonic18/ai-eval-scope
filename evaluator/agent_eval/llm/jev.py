"""Jev（TypeSafe System One）判定模型客户端 — Noul 原语 HTTP 直连。

Jev 是「判定模型」而非对话模型：state + 是/否问题 → P(yes)，无生成能力，
**不继承 LLMClient**（chat 抽象与 noul(state+question) 原语不兼容）；
由 jev_filter（Phase 2）直接构造消费，不进 ProviderPool。

通道绑定（Phase 0 已定，对拍结论仅对此通道成立）：OpenRouter
``POST {base_url}/alpha/decisions``，base_url 缺省 ``https://openrouter.ai/api``；
model 用 slug ``typesafe/jev-1.13``（版本 pin，勿用 ``~typesafe/jev-latest``
漂移别名）；切官方直连须重跑 Phase 0 对拍。

凭证纪律：api_key 仅经 ProviderConfig 注入（llm.json 0600 / 平台 DB），
禁止出现在日志、异常消息与任何落盘产物。
"""

from __future__ import annotations

import json
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import httpx
import structlog

from agent_eval.config import ProviderConfig
from agent_eval.core.exceptions import (
    JevError,
    JevResponseError,
    LLMAuthError,
    LLMError,
    LLMNetworkError,
    LLMRateLimitError,
)

#: OpenRouter 决策端点（Phase 0 验证过的通道；切官方直连时改此常量并重跑对拍）
_DEFAULT_BASE_URL = "https://openrouter.ai/api"
_DECISIONS_PATH = "/alpha/decisions"

#: 瞬时错误（超时/连接中断/429/5xx）重试 1 次（与 Phase 0 对拍 PoC 同口径）
_MAX_RETRIES = 1
_RETRY_DELAY_SEC = 0.5
_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})

LOG = structlog.get_logger("llm.jev")


@dataclass
class NoulQuestion:
    """Noul 是/否判定问题（wire 契约：type=noul + instructions + criteria 双侧定义）。"""

    name: str  # 问题名 = 答案键（answers[name].noul）
    instructions: str  # 判定指令（角色 + 判什么）
    criteria: dict[str, str]  # {"true": 成立定义, "false": 不成立定义}，双侧显式

    def to_body(self) -> dict[str, Any]:
        """转 wire 形态（防御性拷贝，同一问题对象可安全复用）。"""
        return {
            "type": "noul",
            "instructions": self.instructions,
            "criteria": dict(self.criteria),
        }


@dataclass
class JevAnswer:
    """单次 Noul 判定结果。"""

    p_yes: float  # P(yes)（OpenRouter 量化至 2 位小数）
    question_name: str  # 对应问题名
    model: str = ""  # 服务端 resolved 模型快照（如 jev-1.13-20260917），供证据落盘
    latency_ms: float = 0.0
    raw: dict[str, Any] = field(default_factory=dict)  # 完整响应（含 usage/cost）


class _TransientError(Exception):
    """瞬时失败包装（持已分级的 LLMError，重试耗尽时原样抛出）。"""

    def __init__(self, error: LLMError) -> None:
        super().__init__(str(error))
        self.error = error


def _map_status_error(status: int, body_text: str, details: dict[str, Any]) -> LLMError:
    """HTTP 状态 → LLM 分级异常（沿用全系统分级语义，消费方统一按 LLMError 捕获）。"""
    if status == 429:
        return LLMRateLimitError("Jev 限流（HTTP 429）", details=details)
    if status in (401, 403):
        return LLMAuthError(f"Jev 鉴权失败（HTTP {status}）——检查该线路 API Key", details=details)
    if status >= 500:
        return LLMNetworkError(f"Jev 服务端错误（HTTP {status}）", details=details)
    return JevError(f"Jev HTTP {status}: {body_text[:200]}", details=details)


class JevClient:
    """Jev Noul 判定客户端（httpx 直连，复用连接池）。

    httpx.Client 官方支持多线程共享（连接池内部加锁），filter 层
    ThreadPoolExecutor 并发判定可共用单实例。
    """

    def __init__(
        self, name: str, config: ProviderConfig, transport: httpx.BaseTransport | None = None
    ) -> None:
        self._name = name
        self._config = config
        base = (config.base_url or _DEFAULT_BASE_URL).rstrip("/")
        self._url = f"{base}{_DECISIONS_PATH}"
        # timeout 显式化：ProviderConfig 缺省 180s 对秒级判定过宽，Phase 2 由
        # EvaluatorDefaults.jev_timeout_sec 覆写后传入
        self._client = httpx.Client(
            timeout=config.timeout_sec,
            headers={"Authorization": f"Bearer {config.api_key}"},
            transport=transport,
        )

    @property
    def name(self) -> str:
        """线路名（与 ProviderConfig 命名惯例一致，如 "jev"）。"""
        return self._name

    @property
    def model(self) -> str:
        """配置的模型 slug（服务端 resolved 快照随 JevAnswer.model 返回）。"""
        return self._config.model

    def noul(self, question: NoulQuestion, state: Mapping[str, str]) -> JevAnswer:
        """判定一个是/否问题 → JevAnswer。

        Raises:
            LLMNetworkError: 超时/连接中断/5xx，重试 1 次后仍失败。
            LLMRateLimitError: 限流（429），重试 1 次后仍失败。
            LLMAuthError: 鉴权失败（不重试）。
            JevError: 其他非 200 响应。
            JevResponseError: 响应结构异常（缺 answers/noul、数值越界）。
        """
        body = {
            "model": self._config.model,
            "state": dict(state),
            "questions": {question.name: question.to_body()},
        }
        for attempt in range(_MAX_RETRIES + 1):
            try:
                return self._post_once(body, question.name)
            except _TransientError as exc:
                if attempt >= _MAX_RETRIES:
                    raise exc.error from exc
                # 每次重试必须留痕（openai_compat 同款纪律）
                LOG.warning(
                    "jev.noul.retry",
                    provider=self._name,
                    model=self._config.model,
                    attempt=attempt + 1,
                    max_retries=_MAX_RETRIES,
                    error=type(exc.error).__name__,
                    delay_sec=_RETRY_DELAY_SEC,
                )
                time.sleep(_RETRY_DELAY_SEC)
        raise AssertionError("unreachable: 重试循环必在 return/raise 处结束")  # pragma: no cover

    # 预留原语（YAGNI）：choice（多选一）/ score（打分）——落地时扩展
    # questions[name].type 并解析 answers[name].choice / .score，当前不实现。

    def close(self) -> None:
        """释放连接池（常驻进程复用后显式关闭；CLI 一次性进程可省略）。"""
        self._client.close()

    def _post_once(self, body: dict[str, Any], question_name: str) -> JevAnswer:
        start = time.perf_counter()
        try:
            resp = self._client.post(self._url, json=body)
        except httpx.TransportError as e:  # 超时/连接中断均属此族
            raise _TransientError(
                LLMNetworkError(f"Jev 网络错误: {type(e).__name__}", details=self._details())
            ) from e
        if resp.status_code == 200:
            return self._parse_answer(resp, question_name, start)
        error = _map_status_error(resp.status_code, resp.text, self._details())
        if resp.status_code in _RETRYABLE_STATUS:
            raise _TransientError(error)
        raise error

    def _parse_answer(self, resp: httpx.Response, question_name: str, start: float) -> JevAnswer:
        latency_ms = (time.perf_counter() - start) * 1000
        try:
            data = resp.json()
            p_yes = float(data["answers"][question_name]["noul"])
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
            top_keys = sorted(data) if isinstance(data, dict) else type(data).__name__
            raise JevResponseError(
                f"Jev 响应缺 answers.{question_name}.noul 数值（顶层键: {top_keys}）",
                details=self._details(),
            ) from e
        if not 0.0 <= p_yes <= 1.0:
            raise JevResponseError(f"Jev 响应 noul 越界 [0,1]: {p_yes}", details=self._details())
        model = data.get("model") if isinstance(data, dict) else None
        return JevAnswer(
            p_yes=p_yes,
            question_name=question_name,
            model=model if isinstance(model, str) else "",
            latency_ms=latency_ms,
            raw=data,
        )

    def _details(self) -> dict[str, Any]:
        # api_key 永不入详情/日志
        return {"provider": self._name, "model": self._config.model}
