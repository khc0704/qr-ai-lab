"""Declarative base and mixins. Portable across MariaDB (prod) and SQLite (dev/tests)."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import BigInteger, DateTime, Integer
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# BIGINT UNSIGNED on MariaDB; plain INTEGER on SQLite so AUTOINCREMENT works there too.
BigIntPK = BigInteger().with_variant(Integer, "sqlite")
BigInt = BigInteger().with_variant(Integer, "sqlite")
# DATETIME(6) on MariaDB, plain DATETIME elsewhere. All values are naive UTC.
DateTime6 = DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql", "mariadb")


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class IdMixin:
    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime6, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime6, default=utcnow, onupdate=utcnow, nullable=False)
