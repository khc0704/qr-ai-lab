from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, BigInteger, ForeignKey, Index, Integer, Numeric, SmallInteger, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, BigInt, DateTime6, IdMixin, TimestampMixin
from app.models.project import Project
from app.models.user import User

TERMINAL = ("succeeded", "failed", "cancelled")
ACTIVE = ("queued", "scheduled", "running")


class Job(IdMixin, TimestampMixin, Base):
    """Training and inference jobs share one table and one global queue (ordered by queue_rank)."""

    __tablename__ = "jobs"
    __table_args__ = (
        Index("ix_jobs_status_queue_rank", "status", "queue_rank", "created_at"),
        Index("ix_jobs_project_id_created_at", "project_id", "created_at"),
        Index("ix_jobs_kind_status", "kind", "status"),
    )

    project_id: Mapped[int] = mapped_column(BigInt, ForeignKey("projects.id"), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)  # train | inference
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="queued", nullable=False)
    queue_rank: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    requested_gpu: Mapped[int] = mapped_column(SmallInteger, default=0, nullable=False)
    requested_cpu: Mapped[float] = mapped_column(Numeric(5, 2), default=1, nullable=False)
    requested_memory_mb: Mapped[int] = mapped_column(Integer, default=2048, nullable=False)
    timeout_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=240)
    assigned_gpus: Mapped[list[int] | None] = mapped_column(JSON)
    assigned_cpus: Mapped[list[int] | None] = mapped_column(JSON)  # logical CPUs pinned / cpuset for the job
    container_id: Mapped[str | None] = mapped_column(String(64))
    progress: Mapped[float] = mapped_column(Numeric(5, 2), default=0, nullable=False)
    current_stage: Mapped[str | None] = mapped_column(String(64))
    task_type: Mapped[str | None] = mapped_column(String(32))
    mode: Mapped[str | None] = mapped_column(String(32))  # manual | auto (train only)
    model_family: Mapped[str | None] = mapped_column(String(64))
    data_source_id: Mapped[int | None] = mapped_column(
        BigInt, ForeignKey("data_sources.id", ondelete="RESTRICT"), index=True
    )
    artifact_id: Mapped[int | None] = mapped_column(
        BigInt, ForeignKey("artifacts.id", ondelete="RESTRICT", use_alter=True, name="fk_jobs_artifact_id"), index=True
    )
    input: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    config: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    metrics: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    output_path: Mapped[str | None] = mapped_column(String(512))
    log_path: Mapped[str | None] = mapped_column(String(512))
    error_message: Mapped[str | None] = mapped_column(Text)
    cancel_requested_at: Mapped[datetime | None] = mapped_column(DateTime6)
    cancel_requested_by_id: Mapped[int | None] = mapped_column(BigInt, ForeignKey("users.id"))
    cancel_reason: Mapped[str | None] = mapped_column(String(255))
    started_at: Mapped[datetime | None] = mapped_column(DateTime6)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime6)
    created_by_id: Mapped[int] = mapped_column(BigInt, ForeignKey("users.id"), nullable=False)

    project: Mapped[Project] = relationship(lazy="selectin")
    created_by: Mapped[User] = relationship(foreign_keys=[created_by_id], lazy="selectin")
    cancel_requested_by: Mapped[User | None] = relationship(foreign_keys=[cancel_requested_by_id], lazy="selectin")

    @property
    def is_active(self) -> bool:
        return self.status in ACTIVE

    # Denormalised for read schemas (project is always selectin-loaded).
    @property
    def project_slug(self) -> str:
        return self.project.slug

    @property
    def project_name(self) -> str:
        return self.project.name
