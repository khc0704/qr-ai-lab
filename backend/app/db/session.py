from __future__ import annotations

from collections.abc import AsyncIterator
from functools import lru_cache

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings


@lru_cache
def get_engine() -> AsyncEngine:
    s = get_settings()
    kwargs: dict = {"pool_pre_ping": True}
    if s.is_sqlite:
        kwargs = {"connect_args": {"check_same_thread": False}}
    return create_async_engine(s.database_url, **kwargs)


@lru_cache
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with get_sessionmaker()() as session:
        yield session


def reset_db_caches() -> None:
    """Tests swap DATABASE_URL between runs."""
    get_engine.cache_clear()
    get_sessionmaker.cache_clear()
