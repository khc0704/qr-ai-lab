from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class ResourcePool(BaseModel):
    gpu_indices: list[int] = Field(default_factory=list)
    cpu_cores: int = Field(ge=1, le=1024)
    memory_mb: int = Field(ge=1024)
    max_running_jobs: int = Field(ge=1, le=256)
    allow_backfill: bool = True
    # Several jobs on one GPU when they declare requested_gpu_memory_mb and the VRAM is free (pynvml).
    gpu_share: bool = True

    @field_validator("gpu_indices")
    @classmethod
    def _unique_gpu_indices(cls, v: list[int]) -> list[int]:
        if any(i < 0 for i in v):
            raise ValueError("GPU index 不能是負數")
        if len(set(v)) != len(v):
            raise ValueError("GPU index 重複")
        return sorted(v)


class ToolPool(BaseModel):
    """Quota of the shared tool pool (the system project that hosts every preprocessing / analysis job), the
    per-user fairness limit and how long a finished preprocessing result stays downloadable."""

    gpu_limit: int = Field(default=0, ge=0, le=64)
    cpu_limit: float = Field(default=4, ge=0.5)
    memory_limit_mb: int = Field(default=8192, ge=256)
    storage_quota_mb: int = Field(default=4096, ge=64)
    max_concurrent_jobs: int = Field(default=2, ge=1, le=32)
    # queued + running tool jobs one user may hold at once (keeps one person from filling the pool)
    max_jobs_per_user: int = Field(default=2, ge=1, le=32)
    result_ttl_hours: int = Field(default=24, ge=1, le=24 * 30)


class ToolPoolStatus(ToolPool):
    """What a user sees on the tools pages: the pool quota plus their own active tool jobs."""

    my_active_jobs: int = 0
    slug: str = "tools"


class JobDefaults(BaseModel):
    timeout_minutes: int = Field(default=240, ge=1)
    upload_max_mb: int = Field(default=2048, ge=1)
    upload_ttl_minutes: int = Field(default=60, ge=1)
    log_max_mb: int = Field(default=50, ge=1)
