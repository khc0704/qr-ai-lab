from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, BigInteger, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, BigInt, DateTime6, IdMixin, utcnow


class Upload(IdMixin, Base):
    """Transient one-time upload. The file lives under DATA_ROOT/uploads/{id}/ until claimed or expired."""

    __tablename__ = "uploads"
    __table_args__ = (Index("ix_uploads_status_expires_at", "status", "expires_at"),)

    project_id: Mapped[int] = mapped_column(BigInt, ForeignKey("projects.id"), nullable=False, index=True)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    path: Mapped[str] = mapped_column(String(512), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    format: Mapped[str] = mapped_column(String(32), nullable=False)
    detected_spec: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)  # pending | claimed | purged
    claimed_by_job_id: Mapped[int | None] = mapped_column(BigInt, ForeignKey("jobs.id"))
    expires_at: Mapped[datetime] = mapped_column(DateTime6, nullable=False)
    created_by_id: Mapped[int] = mapped_column(BigInt, ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime6, default=utcnow, nullable=False)
