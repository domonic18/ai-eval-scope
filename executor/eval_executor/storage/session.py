"""异步数据库会话 — SQLAlchemy 2.x async + asyncpg。"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from eval_executor.config.settings import Settings, get_settings

_engine_cache: dict[str, AsyncEngine] = {}
_sessionmaker_cache: dict[str, async_sessionmaker[AsyncSession]] = {}


# asyncpg 不识别的 query 参数（Prisma/其他驱动专用），连接前须剥离。
_ASYNCPG_DROP_QUERY_PARAMS = frozenset({"schema"})


def _to_asyncpg_url(url: str) -> str:
    """转 asyncpg 驱动 URL，并剔除 asyncpg 不识别的 query 参数。

    web 的 ``PLATFORM_DATABASE_URL`` 带 ``?schema=public``（Prisma 约定）；asyncpg 会把
    未知 query 参数当作 connect kwargs 报 ``TypeError``，故剥离 schema 等再交给引擎。
    """
    parsed = urlparse(url)
    query = [(k, v) for k, v in parse_qsl(parsed.query) if k not in _ASYNCPG_DROP_QUERY_PARAMS]
    return urlunparse(parsed._replace(scheme="postgresql+asyncpg", query=urlencode(query)))


def get_engine(settings: Settings | None = None) -> AsyncEngine:
    """创建（或复用）异步引擎。"""
    settings = settings or get_settings()
    url = _to_asyncpg_url(settings.database_url)
    if url in _engine_cache:
        return _engine_cache[url]
    engine = create_async_engine(url, future=True, echo=False)
    _engine_cache[url] = engine
    return engine


def make_sessionmaker(settings: Settings | None = None) -> async_sessionmaker[AsyncSession]:
    """创建（或复用）sessionmaker。"""
    settings = settings or get_settings()
    url = _to_asyncpg_url(settings.database_url)
    if url in _sessionmaker_cache:
        return _sessionmaker_cache[url]

    engine = get_engine(settings)
    sm = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    _sessionmaker_cache[url] = sm
    return sm


async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI 依赖：yield 一个 AsyncSession。"""
    sm = make_sessionmaker()
    async with sm() as session:
        try:
            yield session
        finally:
            await session.close()
