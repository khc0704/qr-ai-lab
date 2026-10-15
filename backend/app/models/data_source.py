from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, ForeignKey, LargeBinary, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, BigInt, DateTime6, IdMixin, TimestampMixin
from app.models.user import User


class DataSource(IdMixin, TimestampMixin, Base):
    """A reference to the user's own MinIO/S3 object or an HTTP URL. Never holds data."""

    __tablename__ = "data_sources"
    __table_args__ = (UniqueConstraint("project_id", "name", name="uq_data_sources_project_id_name"),)

    project_id: Mapped[int] = mapped_column(BigInt, ForeignKey("projects.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)  # minio | url
    endpoint: Mapped[str | None] = mapped_column(String(255))
    bucket: Mapped[str | None] = mapped_column(String(128))
    object_path: Mapped[str | None] = mapped_column(String(1024))
    url: Mapped[str | None] = mapped_column(String(2048))
    credentials_enc: Mapped[bytes | None] = mapped_column(LargeBinary(4096))
    format: Mapped[str] = mapped_column(String(32), nullable=False)
    default_spec: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    last_check_ok: Mapped[bool | None] = mapped_column(Boolean)
    last_check_message: Mapped[str | None] = mapped_column(String(255))
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime6)
    created_by_id: Mapped[int] = mapped_column(BigInt, ForeignKey("users.id"), nullable=False)

    created_by: Mapped[User] = relationship(lazy="selectin")
