from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

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


class GpuJobUsage(BaseModel):
    job_id: int
    requested_mb: int | None = None  # None = exclusive
    measured_mb: int = 0  # what the driver attributes to the job's processes right now


class NodeGpu(BaseModel):
    index: int
    name: str
    memory_total_mb: int
    memory_used_mb: int  # driver reading, every process
    utilization: int
    job_id: int | None = None  # first job on this GPU (compat)
    job_ids: list[int] = []  # every job the scheduler placed on this GPU
    jobs: list[GpuJobUsage] = []
    reserved_mb: int | None = None  # Σ requested_gpu_memory_mb of those jobs; None = one of them holds it exclusively
    measured_mb: int | None = None  # Σ measured over our jobs (None when no job is placed here)
    processes: int | None = None  # compute processes seen by the driver (any user)


class GpuResetBody(BaseModel):
    """mode: jobs = force-stop our jobs on the GPU; all = also kill every other process using it;
    device = all + run GPU_RESET_COMMAND (nvidia-smi --gpu-reset)."""

    mode: Literal["jobs", "all", "device"] = "jobs"
    reason: str = Field(min_length=2, max_length=255)


class GpuResetResult(BaseModel):
    index: int
    mode: str
    stopped_jobs: list[int]
    killed_pids: list[int]
    skipped_pids: list[int] = []
    command: str | None = None
    command_ok: bool | None = None
    command_output: str | None = None
    memory_used_mb_before: int | None = None
    memory_used_mb_after: int | None = None


class UsagePoint(BaseModel):
    t: str  # ISO timestamp (bucket start)
    cpu_pct: float | None = None
    mem_used_mb: float | None = None
    gpu_util: float | None = None  # average over the pool's GPUs
    gpu_mem_used_mb: float | None = None  # Σ over the pool's GPUs
    alloc_gpu: float | None = None
    alloc_cpu: float | None = None
    alloc_memory_mb: float | None = None
    running_jobs: float | None = None
    projects: dict[
        str, dict[str, float]
    ] = {}  # project_id → {gpu, cpu, memory_mb, running_jobs, cpu_actual, mem_actual_mb}


class UsageProject(BaseModel):
    id: int
    slug: str
    name: str
    gpu_limit: int
    cpu_limit: float
    memory_limit_mb: int
    status: str


class UsageHistory(BaseModel):
    range: str
    bucket_s: int
    sample_interval_s: int
    points: list[UsagePoint]
    totals: dict[
        str, float
    ]  # node: cpu_cores, memory_mb, gpu_count, gpu_memory_mb; pool: pool_gpu, pool_cpu, pool_memory_mb
    projects: list[UsageProject]
    # per-project share of the *window*: Σ(alloc × seconds) / (limit × window seconds), in percent
    project_share: dict[str, dict[str, float]]


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
    # "wsl2" when the backend runs inside WSL: psutil then reports the WSL VM (its vCPUs and the memory
    # .wslconfig grants it), not the Windows host, so the node numbers differ from Task Manager.
    platform: str | None = None


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
    kind: str = "file"  # file (any single file) | hf_file (one file of a Hugging Face repo) | hf_repo (snapshot)
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
