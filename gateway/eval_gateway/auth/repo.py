"""API Key 数据访问 — 共享 Web 的 PG，只读 api_keys + projects（单一 Bearer token）。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass
class ApiKeyRecord:
    """验签/回传查询结果。"""

    api_key_id: str
    token_hash: str
    token_encrypted: str
    scopes: list[str]
    project_id: str
    org_id: str
    expires_at: datetime | None
    revoked_at: datetime | None


_API_KEY_SQL = text(
    """
    SELECT
        a.id AS api_key_id,
        a.token_hash AS token_hash,
        a.token_encrypted AS token_encrypted,
        a.scopes AS scopes,
        a.expires_at AS expires_at,
        a.revoked_at AS revoked_at,
        p.id AS project_id,
        p.org_id AS org_id
    FROM public.api_keys a
    JOIN public.projects p ON a.project_id = p.id
    WHERE a.token_hash = :token_hash
    """
)


async def find_api_key_by_token_hash(session: AsyncSession, token_hash: str) -> ApiKeyRecord | None:
    """按 token_hash 查 API Key，返回验签所需的全部字段。"""
    result = await session.execute(_API_KEY_SQL, {"token_hash": token_hash})
    row = result.mappings().first()
    if row is None:
        return None

    return _row_to_record(row)


_KEY_BY_ID_SQL = text(
    """
    SELECT
        a.id AS api_key_id,
        a.token_hash AS token_hash,
        a.token_encrypted AS token_encrypted,
        a.scopes AS scopes,
        a.expires_at AS expires_at,
        a.revoked_at AS revoked_at,
        p.id AS project_id,
        p.org_id AS org_id
    FROM public.api_keys a
    JOIN public.projects p ON a.project_id = p.id
    WHERE a.id = :api_key_id
    """
)


async def find_api_key_by_id(session: AsyncSession, api_key_id: str) -> ApiKeyRecord | None:
    """按 id 查 API Key（gateway 回传时解密 token 用）。"""
    result = await session.execute(_KEY_BY_ID_SQL, {"api_key_id": api_key_id})
    row = result.mappings().first()
    if row is None:
        return None
    return _row_to_record(row)


def _row_to_record(row: Any) -> ApiKeyRecord:
    scopes = row["scopes"] or []
    if isinstance(scopes, str):
        scopes = [scopes]
    return ApiKeyRecord(
        api_key_id=row["api_key_id"],
        token_hash=row["token_hash"],
        token_encrypted=row["token_encrypted"],
        scopes=list(scopes),
        project_id=row["project_id"],
        org_id=row["org_id"],
        expires_at=_to_utc(row["expires_at"]),
        revoked_at=_to_utc(row["revoked_at"]),
    )


def _to_utc(value: datetime | None) -> datetime | None:
    """把 naive datetime 视为 UTC。"""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
