"""AuthProvider — 登录引导与会话管理（arch/03 §4.0.2/§4.0.4）。

按 sut_config 的 auth 策略完成登录 → 产出 SUTSession（进程内缓存 + 落盘
持久化，跨运行复用避免重复登录触发风控）；负责过期检测与自动重登频次限制。
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import httpx
from jinja2 import Template as JinjaTemplate

from agent_eval.core.exceptions import SUTAuthError, SUTChannelError
from agent_eval.execution.auth.credentials import CredentialStore
from agent_eval.execution.auth.session import (
    SessionStore,
    SUTSession,
    session_from_login_response,
)
from agent_eval.execution.registry import SUTSystemConfig


class AuthProvider:
    """按 auth.type 策略获取/刷新被测系统会话。"""

    def __init__(
        self,
        sut: SUTSystemConfig,
        *,
        credential_store: CredentialStore | None = None,
        session_store: SessionStore | None = None,
        http_client_factory: Callable[[], httpx.AsyncClient] | None = None,
    ) -> None:
        self.sut = sut
        self.auth = sut.auth
        self.credentials = credential_store or CredentialStore()
        self.sessions = session_store
        self._http_client_factory = http_client_factory
        self._session: SUTSession | None = None
        self._last_auto_relogin: float | None = None

    # ─── 会话获取 ───

    async def get_session(self, *, force: bool = False) -> SUTSession:
        """获取有效会话：内存缓存 → 落盘 → 登录。

        Args:
            force: True 时失效既有会话并强制重新登录（401 自愈路径）。
        """
        if force:
            self.invalidate()
        if self._session is not None and not self._session.is_expired():
            return self._session
        if self.sessions is not None and not force:
            stored = self.sessions.load(self.sut.name)
            if stored is not None:
                self._session = stored
                return stored
        self._session = await self.login()
        if self.sessions is not None:
            self.sessions.save(self._session)
        return self._session

    async def login(self) -> SUTSession:
        """按 auth.type 执行登录，产出 SUTSession。"""
        auth_type = self.auth.type
        if auth_type == "none":
            return SUTSession(sut_name=self.sut.name, expires_at=None)

        if auth_type == "static_token":
            ref = self.auth.credential_ref or self.sut.name
            token = self.credentials.require(ref, "TOKEN")
            extract = self.auth.extract
            return SUTSession(
                sut_name=self.sut.name,
                token=token,
                token_type=extract.token_type if extract else "Bearer",
                mount_header=self.auth.mount.header,
                expires_at=None,  # 长期有效
            )

        if auth_type in ("api_login", "session_cookie"):
            return await self._login_by_api()

        raise SUTAuthError(f"未支持的鉴权类型: {auth_type!r}")

    def invalidate(self) -> None:
        """失效会话（内存 + 落盘）。"""
        self._session = None
        if self.sessions is not None:
            self.sessions.invalidate(self.sut.name)

    def mount_headers(self, session: SUTSession) -> dict[str, str]:
        """业务请求自动挂载的凭证头。"""
        return session.mount_headers()

    # ─── 自动重登频次限制（§4.0.4：默认每系统 30 分钟 ≤ 1 次） ───

    def auto_relogin_allowed(self) -> bool:
        """检查自动重登是否在频次窗口内允许。"""
        if self._last_auto_relogin is None:
            return True
        return (time.time() - self._last_auto_relogin) >= self.auth.relogin_window_s

    def mark_auto_relogin(self) -> None:
        """记录一次自动重登时间戳。"""
        self._last_auto_relogin = time.time()

    # ─── 内部 ───

    async def _login_by_api(self) -> SUTSession:
        """api_login / session_cookie：渲染账密 → 请求登录接口 → 提取凭证。"""
        login = self.auth.login
        if login is None:
            raise SUTAuthError(
                f"auth.type={self.auth.type!r} 需要配置 auth.login 段（method/path/body_template）",
                details={"sut": self.sut.name},
            )
        ref = self.auth.credential_ref or self.sut.name
        # 凭证键名由模板声明（通用 KV，06 §4.7）：body_template 写 {{ account }}
        # 就取 ref.account——不预设 username/password 字段集
        from agent_eval.execution.auth.credentials import required_credential_fields

        context = {
            field.lower(): self.credentials.require(ref, field)
            for field in required_credential_fields(self.sut)
        }
        body = JinjaTemplate(login.body_template).render(**context)
        if login.path.startswith(("http://", "https://")):
            url = login.path
        else:
            url = f"{self.sut.base_url.rstrip('/')}/{login.path.lstrip('/')}"
        client_cm = (
            self._http_client_factory()
            if self._http_client_factory
            else httpx.AsyncClient(timeout=self.sut.timeout)
        )
        try:
            async with client_cm as client:
                response = await client.request(
                    method=login.method.upper(),
                    url=url,
                    content=body,
                    headers={"Content-Type": "application/json"},
                )
        except httpx.HTTPError as e:
            raise SUTAuthError(
                f"登录请求失败: {e}", details={"sut": self.sut.name, "url": url}
            ) from e
        if response.status_code >= 400:
            raise SUTAuthError(
                f"登录失败（HTTP {response.status_code}）",
                details={"sut": self.sut.name, "url": url, "body": response.text[:500]},
            )
        try:
            payload: dict[str, Any] = response.json()
        except ValueError as e:
            raise SUTAuthError(f"登录响应不是合法 JSON: {e}", details={"sut": self.sut.name}) from e

        from agent_eval.execution.registry import AuthExtractConfig

        extract = self.auth.extract or AuthExtractConfig()
        expires_in = None
        if extract.expires_in_path:
            from agent_eval.execution.utils import extract_by_path

            expires_in = float(extract_by_path(payload, extract.expires_in_path))
        # session_cookie：登录态由共享 client 的 cookie jar 承载，仅记录有效期
        token_type = "cookie" if self.auth.type == "session_cookie" else extract.token_type
        session = session_from_login_response(
            sut_name=self.sut.name,
            payload=payload,
            token_path=extract.token_path,
            token_type=token_type,
            mount_header=self.auth.mount.header,
            expires_in=expires_in,
        )
        if self.auth.type == "api_login" and not session.token:
            raise SUTChannelError(
                "api_login 登录响应中未提取到 token（检查 auth.extract.token_path）",
                details={"sut": self.sut.name},
            )
        return session
