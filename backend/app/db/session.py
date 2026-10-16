from __future__ import annotations

from collections.abc import AsyncIterator
from functools import lru_cache

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings


@lru_cache
def get_engine() -> AsyncEngine:
    s = get_settings()
    kwargs: dict = {"pool_pre_ping": True}
    if s.is_sqlite:
        kwargs = {"connect_args": {"check_same_thread": False}}
    engine = create_async_engine(s.database_url, **kwargs)
    if s.is_sqlite:

        @event.listens_for(engine.sync_engine, "connect")
        def _enable_foreign_keys(dbapi_connection, _record) -> None:
            # SQLite ignores FKs unless asked; dev / tests must behave like MariaDB (RESTRICT, SET NULL …).
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


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
