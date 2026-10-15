from __future__ import annotations

from typing import Any

from sqlalchemy import JSON, BigInteger, Boolean, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, BigInt, IdMixin, TimestampMixin


class Artifact(IdMixin, TimestampMixin, Base):
    __tablename__ = "artifacts"
    __table_args__ = (
        UniqueConstraint("project_id", "name", "version", name="uq_artifacts_project_id_name_version"),
        Index("ix_artifacts_project_id_kind", "project_id", "kind"),
    )

    project_id: Mapped[int] = mapped_column(BigInt, ForeignKey("projects.id"), nullable=False)
    job_id: Mapped[int] = mapped_column(BigInt, ForeignKey("jobs.id", ondelete="RESTRICT"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)  # model | weights | preprocessor | report | metrics
    model_family: Mapped[str] = mapped_column(String(64), nullable=False)
    framework: Mapped[str] = mapped_column(String(32), nullable=False)
    path: Mapped[str] = mapped_column(String(512), nullable=False)  # relative to DATA_ROOT
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    metrics: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    metadata_: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSON)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
