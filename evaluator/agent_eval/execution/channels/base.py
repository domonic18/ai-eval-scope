"""SUTChannel 通道基座（arch/03 §4.0.1）。

统一"向被测系统发起一次交互"的公共机制：共享 AsyncClient（连接池 + cookie
jar，同一运行内复用）、凭证自动挂载、401/403 自动重登一次并重放（含频次
限制，防自动化登录触发风控）。具体协议语义由子类实现。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any

import httpx

from agent_eval.core.exceptions import SUTAuthError, SUTChannelError
from agent_eval.execution.auth.provider import AuthProvider
from agent_eval.execution.registry import SUTSystemConfig


class SUTChannel(ABC):
    """被测系统通道抽象基座。"""

    channel_type: str = "base"

    def __init__(
        self,
        sut: SUTSystemConfig,
        *,
        auth_provider: AuthProvider | None = None,
        http_client_factory: Callable[[], httpx.AsyncClient] | None = None,
    ) -> None:
        self.sut = sut
        # http_client_factory 同时传给 AuthProvider（登录请求与业务请求共享注入的 Mock）
        self.auth = auth_provider or AuthProvider(sut, http_client_factory=http_client_factory)
        self._http_client_factory = http_client_factory
        self._client: httpx.AsyncClient | None = None

    @property
    def client(self) -> httpx.AsyncClient:
        """共享 AsyncClient（连接池 + cookie jar；测试可注入 MockTransport 工厂）。"""
        if self._client is None:
            if self._http_client_factory:
                self._client = self._http_client_factory()
            else:
                self._client = httpx.AsyncClient(timeout=self.sut.timeout)
        return self._client

    async def aclose(self) -> None:
        """关闭共享客户端。"""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    @abstractmethod
    async def health_check(self) -> dict[str, Any]:
        """通道健康检查（接入自检）。"""

    async def request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        params: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> httpx.Response:
        """发起一次鉴权请求：挂载凭证 → 401/403 自动重登一次并重放。

        Args:
            method: HTTP 方法。
            path: 相对 base_url 的路径。
            json_body: JSON 请求体。
            headers: 附加请求头（不得含凭证，凭证由会话自动挂载）。
            params: 查询参数。
            timeout: 覆盖超时（秒）。
        """
        url = f"{self.sut.base_url.rstrip('/')}/{path.lstrip('/')}"
        session = await self.auth.get_session()
        merged = {**session.mount_headers(), **(headers or {})}
        try:
            response = await self.client.request(
                method=method.upper(),
                url=url,
                json=json_body,
                headers=merged or None,
                params=params,
                timeout=timeout or self.sut.timeout,
            )
        except httpx.HTTPError as e:
            raise SUTChannelError(
                f"SUT 请求失败: {e}", details={"sut": self.sut.name, "url": url}
            ) from e

        if response.status_code in (401, 403) and self.auth.auth.type != "none":
            # 会话失效自愈：自动重登一次并重放（频次限制内）
            if not self.auth.auto_relogin_allowed():
                raise SUTAuthError(
                    f"会话失效且自动重登超出频次限制（窗口 {self.auth.auth.relogin_window_s} 秒）",
                    details={"sut": self.sut.name, "status_code": response.status_code},
                )
            self.auth.mark_auto_relogin()
            session = await self.auth.get_session(force=True)
            replay_headers = {**session.mount_headers(), **(headers or {})}
            try:
                response = await self.client.request(
                    method=method.upper(),
                    url=url,
                    json=json_body,
                    headers=replay_headers or None,
                    params=params,
                    timeout=timeout or self.sut.timeout,
                )
            except httpx.HTTPError as e:
                raise SUTChannelError(
                    f"SUT 重放请求失败: {e}", details={"sut": self.sut.name, "url": url}
                ) from e
        return response


def create_channel(
    sut: SUTSystemConfig,
    *,
    http_client_factory: Callable[[], httpx.AsyncClient] | None = None,
) -> SUTChannel:
    """按 sut.channel 构建通道实例（工厂；预留通道给出友好错误）。"""
    if sut.channel == "agent_protocol":
        from agent_eval.execution.channels.agent_protocol import AgentProtocolChannel

        return AgentProtocolChannel(sut, http_client_factory=http_client_factory)
    raise SUTChannelError(
        f"通道 {sut.channel!r} 预留未排期（本期唯一排期通道为 agent_protocol，arch/03 §4.0.6）",
        details={"sut": sut.name, "channel": sut.channel},
    )
