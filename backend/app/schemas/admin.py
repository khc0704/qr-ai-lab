from __future__ import annotations

from datetime import datetime
from typing import Any

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


class NodeStatus(BaseModel):
    gpus: list[NodeGpu]
    cpu_cores: int
    cpu_used_cores: float
    memory_mb: int
    memory_used_mb: int
    disk_total_gb: int
    disk_free_gb: int
    allocated: Allocated


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


class ModelZooEntry(BaseModel):
    id: str
    family: str
    file: str
    license: str | None = None
    source: str | None = None
    kind: str = "file"
    present: bool
    size_bytes: int | None = None
    sha256_expected: str | None = None
    sha256_actual: str | None = None
