"""FastAPI 鉴权依赖 — 复刻 web/backend/src/middleware/apiKeyAuth.ts。

流程：解析 Authorization → 查库 → 校验 revoked/expires/scopes → 解密 secret →
重算 HMAC（基于原始 body）→ 常量时间比较 → 把 tenant 注入 request.state。

raw body 获取：直接 `await request.body()`（Starlette 会缓存到 request._body），
不使用 BaseHTTPMiddleware（其会破坏下游 form()/json() 对 body 的复用）。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import HTTPException, Request, status

from eval_gateway.auth.crypto import decrypt_secret, hmac_verify, parse_auth_header
from eval_gateway.auth.repo import find_api_key_by_public_key
from eval_gateway.config.settings import get_settings
from eval_gateway.core.logging import get_logger
from eval_gateway.storage.session import get_async_session

LOG = get_logger(__name__)


@dataclass
class Tenant:
    """当前 API Key 所属租户上下文。"""

    api_key_id: str
    project_id: str
    org_id: str
    scopes: list[str]


async def verify_api_key(request: Request) -> Tenant:
    """FastAPI 依赖：验证 HMAC 签名并返回 Tenant。

    失败时抛出 401 HTTPException，与 web 行为一致。
    """
    header = request.headers.get("authorization")
    parsed = parse_auth_header(header)
    if parsed is None:
        raise _unauthorized()

    async for session in get_async_session():  # noqa: ASYNC102
        key = await find_api_key_by_public_key(session, parsed.public_key)
    if key is None:
        raise _unauthorized()

    if key.revoked_at is not None:
        raise _unauthorized("key revoked")
    if key.expires_at is not None and key.expires_at < datetime.now(UTC):
        raise _unauthorized("key expired")
    if "ingest" not in key.scopes:
        raise _unauthorized("scope denied")

    settings = get_settings()
    try:
        secret = decrypt_secret(key.secret_encrypted, settings.key_encryption_key)
    except Exception as exc:  # noqa: BLE001
        LOG.warning("decrypt_secret.failed", api_key_id=key.api_key_id, error=str(exc))
        raise _unauthorized() from exc

    raw_body = await request.body()
    path = request.url.path  # 不带 query string，与 web originalUrl.split('?')[0] 一致
    if not hmac_verify(secret, request.method, path, raw_body, parsed.signature):
        raise _unauthorized("signature mismatch")

    tenant = Tenant(
        api_key_id=key.api_key_id,
        project_id=key.project_id,
        org_id=key.org_id,
        scopes=key.scopes,
    )
    request.state.tenant = tenant
    return tenant


def _unauthorized(detail: str = "invalid api key or signature") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"error": detail, "code": "AUTH_INVALID"},
    )
