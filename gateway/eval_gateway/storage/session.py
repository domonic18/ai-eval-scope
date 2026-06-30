"""异步数据库会话 — SQLAlchemy 2.x async + asyncpg。"""

from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from eval_gateway.config.settings import Settings, get_settings

_engine_cache: dict[str, AsyncEngine] = {}
_sessionmaker_cache: dict[str, async_sessionmaker[AsyncSession]] = {}


def _to_asyncpg_url(url: str) -> str:
    """把标准 postgresql:// 转换为 asyncpg 驱动的 postgresql+asyncpg://。"""
    if url.startswith("postgresql://"):
        return "postgresql+asyncpg://" + url[len("postgresql://") :]
    if url.startswith("postgres://"):
        return "postgresql+asyncpg://" + url[len("postgres://") :]
    return url


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
