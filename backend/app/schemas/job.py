from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel
from app.schemas.user import UserRead


class JobInputBody(BaseModel):
    kind: Literal["upload", "data_source", "inline"]
    upload_id: int | None = None
    data_source_id: int | None = None
    format: str | None = None
    spec: dict[str, Any] = Field(default_factory=dict)
    rows: list[dict[str, Any]] | None = None  # inline (inference only)


MAX_TIMEOUT_MINUTES = 14 * 24 * 60  # two weeks; the per-job token lives as long


class JobCreate(BaseModel):
    kind: Literal["train", "inference"]
    name: str = Field(min_length=1, max_length=120)
    input: JobInputBody
    task_type: str | None = None
    mode: Literal["manual", "auto"] | None = None
    model_family: str | None = None
    config: dict[str, Any] | None = None
    artifact_id: int | None = None
    requested_gpu: int = Field(default=0, ge=0, le=64)
    requested_cpu: float = Field(default=1, ge=0.5, le=999)  # jobs.requested_cpu is NUMERIC(5,2)
    requested_memory_mb: int = Field(default=2048, ge=256)
    # VRAM this job needs per GPU. Set → the scheduler may place it on a GPU another job is using as long as
    # that much memory is free (and the trainer caps itself with set_per_process_memory_fraction). None → exclusive.
    requested_gpu_memory_mb: int | None = Field(default=None, ge=256, le=1024 * 1024)
    timeout_minutes: int | None = Field(default=None, ge=1, le=MAX_TIMEOUT_MINUTES)
    # One-off inference (inference only): the server picks the resources, nothing is registered as an artifact,
    # the job is hidden from the job lists and expires with its outputs after the result TTL.
    ephemeral: bool = False


class JobRead(ORMModel):
    id: int
    project_id: int
    project_slug: str
    project_name: str
    kind: str
    name: str
    status: str
    ephemeral: bool = False
    queue_rank: int
    queue_position: int | None = None
    wait_reason: str | None = None
    requested_gpu: int
    requested_cpu: float
    requested_memory_mb: int
    requested_gpu_memory_mb: int | None = None
    timeout_minutes: int
    assigned_gpus: list[int] | None
    assigned_cpus: list[int] | None = None
    progress: float
    current_stage: str | None
    task_type: str | None
    mode: str | None
    model_family: str | None
    data_source_id: int | None
    artifact_id: int | None
    input: dict[str, Any]
    config: dict[str, Any] | None
    metrics: dict[str, Any] | None
    result: dict[str, Any] | None
    output_path: str | None
    error_message: str | None
    cancel_reason: str | None
    cancel_requested_by: UserRead | None
    started_at: datetime | None
    finished_at: datetime | None
    created_by: UserRead
    created_at: datetime


class LogLinesRead(BaseModel):
    lines: list[str]
    offset: int
    total: int
    last_event_id: str | None = None  # send as Last-Event-ID to /events so the replay does not repeat these lines


class StopBody(BaseModel):
    reason: str = Field(min_length=2, max_length=255)


class OrderBody(BaseModel):
    job_ids: list[int] = Field(min_length=1)


class JobIdsBody(BaseModel):
    job_ids: list[int] = Field(min_length=1, max_length=200)


class SkippedJob(BaseModel):
    id: int
    code: str
    message: str


class JobsDeleteResult(BaseModel):
    deleted: list[int]
    skipped: list[SkippedJob]


class MoveBody(BaseModel):
    position: Literal["top", "up", "down", "bottom"]
