from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, BigInt, DateTime6, utcnow


class SystemSetting(Base):
    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    updated_by_id: Mapped[int | None] = mapped_column(BigInt, ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime6, default=utcnow, onupdate=utcnow, nullable=False)
