from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, BigInt, DateTime6, IdMixin, TimestampMixin
from app.models.user import User


class Issue(IdMixin, TimestampMixin, Base):
    __tablename__ = "issues"
    __table_args__ = (
        Index("ix_issues_status_created_at", "status", "created_at"),
        Index("ix_issues_type_status", "type", "status"),
    )

    type: Mapped[str] = mapped_column(String(32), nullable=False)  # question | bug | feature
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(32), default="open", nullable=False)  # open | closed
    author_id: Mapped[int] = mapped_column(BigInt, ForeignKey("users.id"), nullable=False, index=True)
    assignee_id: Mapped[int | None] = mapped_column(BigInt, ForeignKey("users.id"))
    project_id: Mapped[int | None] = mapped_column(BigInt, ForeignKey("projects.id"), index=True)
    resolution_note: Mapped[str | None] = mapped_column(Text)
    closed_by_id: Mapped[int | None] = mapped_column(BigInt, ForeignKey("users.id"))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime6)
    comment_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    author: Mapped[User] = relationship(foreign_keys=[author_id], lazy="selectin")
    assignee: Mapped[User | None] = relationship(foreign_keys=[assignee_id], lazy="selectin")
