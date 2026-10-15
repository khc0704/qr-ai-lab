from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, ForeignKey, Index, Integer, Numeric, SmallInteger, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, BigInt, DateTime6, IdMixin, TimestampMixin, utcnow
from app.models.user import User


class Project(IdMixin, TimestampMixin, Base):
    __tablename__ = "projects"
    __table_args__ = (Index("ix_projects_status_created_at", "status", "created_at"),)

    slug: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    data_type: Mapped[str] = mapped_column(String(32), nullable=False)
    task_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)  # active | archived
    owner_id: Mapped[int] = mapped_column(BigInt, ForeignKey("users.id"), nullable=False, index=True)
    request_id: Mapped[int | None] = mapped_column(BigInt, ForeignKey("project_requests.id"), unique=True)
    gpu_limit: Mapped[int] = mapped_column(SmallInteger, default=0, nullable=False)
    cpu_limit: Mapped[float] = mapped_column(Numeric(5, 2), default=2, nullable=False)
    memory_limit_mb: Mapped[int] = mapped_column(Integer, default=4096, nullable=False)
    storage_quota_mb: Mapped[int] = mapped_column(Integer, default=10240, nullable=False)
    storage_used_bytes: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    max_concurrent_jobs: Mapped[int] = mapped_column(SmallInteger, default=1, nullable=False)
    default_job_timeout_minutes: Mapped[int | None] = mapped_column(Integer)
    approved_by_id: Mapped[int | None] = mapped_column(BigInt, ForeignKey("users.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime6)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime6)

    owner: Mapped[User] = relationship(foreign_keys=[owner_id], lazy="selectin")
    members: Mapped[list[ProjectMember]] = relationship(
        back_populates="project", lazy="selectin", cascade="all, delete-orphan"
    )

    def role_of(self, user_id: int) -> str | None:
        for m in self.members:
            if m.user_id == user_id:
                return m.role
        return None


class ProjectMember(Base):
    __tablename__ = "project_members"

    project_id: Mapped[int] = mapped_column(BigInt, ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInt, ForeignKey("users.id"), primary_key=True, index=True)
    role: Mapped[str] = mapped_column(String(32), nullable=False)  # owner | maintainer | member | viewer
    added_by_id: Mapped[int | None] = mapped_column(BigInt, ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime6, default=utcnow, nullable=False)

    project: Mapped[Project] = relationship(back_populates="members")
    user: Mapped[User] = relationship(foreign_keys=[user_id], lazy="selectin")
