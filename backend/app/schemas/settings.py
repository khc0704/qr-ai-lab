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


class ToolDefaults(BaseModel):
    """Quota of every user's personal workspace (the project that hosts preprocessing / analysis tool jobs) and
    how long a finished preprocessing result stays downloadable."""

    gpu_limit: int = Field(default=0, ge=0, le=64)
    cpu_limit: float = Field(default=2, ge=0.5)
    memory_limit_mb: int = Field(default=4096, ge=256)
    storage_quota_mb: int = Field(default=2048, ge=64)
    max_concurrent_jobs: int = Field(default=1, ge=1, le=16)
    result_ttl_hours: int = Field(default=24, ge=1, le=24 * 30)


class JobDefaults(BaseModel):
    timeout_minutes: int = Field(default=240, ge=1)
    upload_max_mb: int = Field(default=2048, ge=1)
    upload_ttl_minutes: int = Field(default=60, ge=1)
    log_max_mb: int = Field(default=50, ge=1)
