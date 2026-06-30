"""API Key 数据访问 — 共享 Web 的 PG，只读 api_keys + projects。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass
class ApiKeyRecord:
    """验签查询结果。"""

    api_key_id: str
    public_key: str
    secret_encrypted: str
    scopes: list[str]
    project_id: str
    org_id: str
    expires_at: datetime | None
    revoked_at: datetime | None


_API_KEY_SQL = text(
    """
    SELECT
        a.id AS api_key_id,
        a.public_key AS public_key,
        a.secret_encrypted AS secret_encrypted,
        a.scopes AS scopes,
        a.expires_at AS expires_at,
        a.revoked_at AS revoked_at,
        p.id AS project_id,
        p.org_id AS org_id
    FROM public.api_keys a
    JOIN public.projects p ON a.project_id = p.id
    WHERE a.public_key = :public_key
    """
)


async def find_api_key_by_public_key(session: AsyncSession, public_key: str) -> ApiKeyRecord | None:
    """按 public_key 查 API Key，返回验签所需的全部字段。"""
    result = await session.execute(_API_KEY_SQL, {"public_key": public_key})
    row = result.mappings().first()
    if row is None:
        return None

    scopes = row["scopes"] or []
    if isinstance(scopes, str):
        scopes = [scopes]

    return ApiKeyRecord(
        api_key_id=row["api_key_id"],
        public_key=row["public_key"],
        secret_encrypted=row["secret_encrypted"],
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
