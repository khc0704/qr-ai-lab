from __future__ import annotations

from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, BigInt, IdMixin, TimestampMixin
from app.models.user import User


class Comment(IdMixin, TimestampMixin, Base):
    """Polymorphic comments for issues and project requests (target_type + target_id, no FK)."""

    __tablename__ = "comments"
    __table_args__ = (Index("ix_comments_target", "target_type", "target_id", "created_at"),)

    target_type: Mapped[str] = mapped_column(String(32), nullable=False)  # issue | project_request
    target_id: Mapped[int] = mapped_column(BigInt, nullable=False)
    author_id: Mapped[int | None] = mapped_column(BigInt, ForeignKey("users.id"))
    kind: Mapped[str] = mapped_column(String(32), default="comment", nullable=False)  # comment | system
    body: Mapped[str] = mapped_column(Text, nullable=False)

    author: Mapped[User | None] = relationship(lazy="selectin")
