from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, ForeignKey, Index, Integer, Numeric, SmallInteger, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, BigInt, DateTime6, IdMixin, TimestampMixin, utcnow
from app.models.user import User


class ProjectRequest(IdMixin, TimestampMixin, Base):
    __tablename__ = "project_requests"
    __table_args__ = (Index("ix_project_requests_status_submitted_at", "status", "submitted_at"),)

    applicant_id: Mapped[int] = mapped_column(BigInt, ForeignKey("users.id"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    purpose: Mapped[str] = mapped_column(Text, nullable=False)
    data_type: Mapped[str] = mapped_column(String(32), nullable=False)
    task_type: Mapped[str] = mapped_column(String(32), nullable=False)
    data_scale: Mapped[str] = mapped_column(String(32), nullable=False)
    data_description: Mapped[str | None] = mapped_column(Text)
    requested_gpu: Mapped[int] = mapped_column(SmallInteger, default=0, nullable=False)
    requested_cpu: Mapped[float] = mapped_column(Numeric(5, 2), default=2, nullable=False)
    requested_memory_mb: Mapped[int] = mapped_column(Integer, default=4096, nullable=False)
    requested_storage_mb: Mapped[int] = mapped_column(Integer, default=10240, nullable=False)
    proposed_slug: Mapped[str | None] = mapped_column(String(64))
    members: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(32), default="submitted", nullable=False)
    reviewer_id: Mapped[int | None] = mapped_column(BigInt, ForeignKey("users.id"))
    review_note: Mapped[str | None] = mapped_column(Text)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime6)
    project_id: Mapped[int | None] = mapped_column(
        BigInt, ForeignKey("projects.id", use_alter=True, name="fk_project_requests_project_id"), unique=True
    )
    submitted_at: Mapped[datetime] = mapped_column(DateTime6, default=utcnow, nullable=False)
    comment_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    applicant: Mapped[User] = relationship(foreign_keys=[applicant_id], lazy="selectin")
    reviewer: Mapped[User | None] = relationship(foreign_keys=[reviewer_id], lazy="selectin")
