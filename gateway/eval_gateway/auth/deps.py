"""FastAPI 鉴权依赖 — 复刻 web/backend/src/middleware/apiKeyAuth.ts（Bearer）。

流程：解析 Authorization: Bearer <token> → sha256(token) 查库 →
校验 revoked/expires/scopes → 把 tenant 注入 request.state。

Bearer 无需读取/校验请求体（无签名），下游 form()/json() 可正常复用 body。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import HTTPException, Request, status

from eval_gateway.auth.crypto import hash_token, parse_bearer_token
from eval_gateway.auth.repo import find_api_key_by_token_hash
from eval_gateway.storage.session import get_async_session


@dataclass
class Tenant:
    """当前 API Key 所属租户上下文。"""

    api_key_id: str
    project_id: str
    org_id: str
    scopes: list[str]


async def verify_api_key(request: Request) -> Tenant:
    """FastAPI 依赖：验证 Bearer token 并返回 Tenant。

    失败时抛出 401 HTTPException，与 web 行为一致。
    """
    header = request.headers.get("authorization")
    token = parse_bearer_token(header)
    if token is None:
        raise _unauthorized()

    async for session in get_async_session():  # noqa: ASYNC102
        key = await find_api_key_by_token_hash(session, hash_token(token))
    if key is None:
        raise _unauthorized()

    if key.revoked_at is not None:
        raise _unauthorized("key revoked")
    if key.expires_at is not None and key.expires_at < datetime.now(UTC):
        raise _unauthorized("key expired")
    if "ingest" not in key.scopes:
        raise _unauthorized("scope denied")

    tenant = Tenant(
        api_key_id=key.api_key_id,
        project_id=key.project_id,
        org_id=key.org_id,
        scopes=key.scopes,
    )
    request.state.tenant = tenant
    return tenant


def _unauthorized(detail: str = "invalid api key") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"error": detail, "code": "AUTH_INVALID"},
    )
