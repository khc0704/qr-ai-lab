from __future__ import annotations

from pydantic import BaseModel, Field


class ResourcePool(BaseModel):
    gpu_indices: list[int] = Field(default_factory=list)
    cpu_cores: int = Field(ge=1, le=1024)
    memory_mb: int = Field(ge=1024)
    max_running_jobs: int = Field(ge=1, le=256)
    allow_backfill: bool = True
    # Several jobs on one GPU when they declare requested_gpu_memory_mb and the VRAM is free (pynvml).
    gpu_share: bool = True


class JobDefaults(BaseModel):
    timeout_minutes: int = Field(default=240, ge=1)
    upload_max_mb: int = Field(default=2048, ge=1)
    upload_ttl_minutes: int = Field(default=60, ge=1)
    log_max_mb: int = Field(default=50, ge=1)
