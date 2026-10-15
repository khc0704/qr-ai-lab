from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel

from app.schemas.common import ORMModel
from app.schemas.job import JobRead
from app.schemas.settings import ResourcePool
from app.schemas.user import UserRead


class AdminOverview(BaseModel):
    pending_requests: int
    queued: int
    running: int
    pool_gpu_used: int
    pool_gpu_total: int
    pool_utilization: int


class NodeGpu(BaseModel):
    index: int
    name: str
    memory_total_mb: int
    memory_used_mb: int
    utilization: int
    job_id: int | None = None


class Allocated(BaseModel):
    gpu: int = 0
    cpu: float = 0
    memory_mb: int = 0
    running_jobs: int = 0


class RunnerInfo(BaseModel):
    """How jobs are executed on this host (no containers): which limits the kernel enforces and which the
    scheduler's watchdog covers."""

    kind: str  # systemd | subprocess
    enforces: dict[str, bool]  # memory / cpu / cpuset
    memory_watchdog: bool
    trainer_python: str
    trainer_dir: str
    offline: bool = True
    note: str = ""


class NodeStatus(BaseModel):
    gpus: list[NodeGpu]
    cpu_cores: int
    cpu_used_cores: float
    memory_mb: int
    memory_used_mb: int
    disk_total_gb: int
    disk_free_gb: int
    allocated: Allocated
    runner: RunnerInfo | None = None


class CapacityRead(BaseModel):
    pool: ResourcePool
    allocated: Allocated


class QueueRead(BaseModel):
    running: list[JobRead]
    queued: list[JobRead]


class AuditLogRead(ORMModel):
    id: int
    actor: UserRead | None
    action: str
    target_type: str
    target_id: int | None
    payload: dict[str, Any] | None
    created_at: datetime


class ZooTask(BaseModel):
    """Progress of a background import (url / path) for one weight id."""

    weight_id: str
    source: str
    state: str  # running | done | error
    progress: float = 0  # 0..1 when the size is known
    downloaded_mb: float = 0
    total_mb: float | None = None
    message: str | None = None
    started_at: str
    finished_at: str | None = None


class ModelZooEntry(BaseModel):
    id: str
    family: str
    families: list[str] = []
    file: str
    license: str | None = None
    source: str | None = None
    kind: str = "file"  # file | hf_repo
    present: bool
    status: str = "missing"  # present | missing | mismatch | importing | error
    size_bytes: int | None = None
    sha256_expected: str | None = None
    sha256_actual: str | None = None
    imported_at: str | None = None
    imported_from: str | None = None
    task: ZooTask | None = None


class ZooImportBody(BaseModel):
    source: Literal["url", "path"]
    url: str | None = None
    path: str | None = None
