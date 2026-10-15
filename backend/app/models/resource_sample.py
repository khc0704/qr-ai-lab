from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, BigInt, DateTime6, utcnow


class ResourceSample(Base):
    """One point of the usage history (written by the scheduler every USAGE_SAMPLE_INTERVAL_S seconds).

    payload = {
      "node": {"cpu_pct", "cpu_cores", "mem_used_mb", "mem_total_mb",
               "gpus": [{"index", "util", "mem_used_mb", "mem_total_mb"}]},
      "pool": {"gpu", "cpu", "memory_mb", "running_jobs", "gpu_total", "cpu_total", "memory_total_mb"},
      "projects": {"<project_id>": {"gpu", "cpu", "memory_mb", "running_jobs", "cpu_actual", "mem_actual_mb"}},
    }
    Allocated numbers are what the scheduler granted; *_actual are measured on the job processes.
    """

    __tablename__ = "resource_samples"
    __table_args__ = (Index("ix_resource_samples_sampled_at", "sampled_at"),)

    id: Mapped[int] = mapped_column(BigInt, primary_key=True, autoincrement=True)
    sampled_at: Mapped[datetime] = mapped_column(DateTime6, default=utcnow, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
