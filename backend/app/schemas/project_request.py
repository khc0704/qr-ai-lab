from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel
from app.schemas.user import UserRead

DataType = Literal["TABULAR", "IMAGE", "SEQUENCE", "TEXT", "SPECTRUM"]
TaskType = Literal["classification", "regression", "detection", "segmentation", "anomaly_detection"]
DataScale = Literal["tiny", "small", "medium", "large"]
MemberRole = Literal["maintainer", "member", "viewer"]
SLUG = r"^[a-z0-9][a-z0-9-]{1,62}$"


class MemberEmail(BaseModel):
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    role: MemberRole = "member"


class ProjectRequestCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    purpose: str = Field(min_length=1)
    data_type: DataType
    task_type: TaskType
    data_scale: DataScale
    data_description: str | None = None
    requested_gpu: int = Field(default=0, ge=0, le=64)
    requested_cpu: float = Field(default=2, ge=0.5, le=1024)
    requested_memory_mb: int = Field(default=4096, ge=512)
    requested_storage_mb: int = Field(default=10240, ge=1024)
    proposed_slug: str | None = Field(default=None, pattern=SLUG)
    members: list[MemberEmail] = Field(default_factory=list)


class ProjectRequestUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    purpose: str | None = None
    data_type: DataType | None = None
    task_type: TaskType | None = None
    data_scale: DataScale | None = None
    data_description: str | None = None
    requested_gpu: int | None = Field(default=None, ge=0, le=64)
    requested_cpu: float | None = Field(default=None, ge=0.5)
    requested_memory_mb: int | None = Field(default=None, ge=512)
    requested_storage_mb: int | None = Field(default=None, ge=1024)
    proposed_slug: str | None = Field(default=None, pattern=SLUG)
    members: list[MemberEmail] | None = None


class ProjectRequestRead(ORMModel):
    id: int
    applicant: UserRead
    title: str
    purpose: str
    data_type: str
    task_type: str
    data_scale: str
    data_description: str | None
    requested_gpu: int
    requested_cpu: float
    requested_memory_mb: int
    requested_storage_mb: int
    proposed_slug: str | None
    members: list[MemberEmail] | None
    status: str
    reviewer: UserRead | None
    review_note: str | None
    reviewed_at: datetime | None
    project_slug: str | None = None
    comment_count: int
    submitted_at: datetime
    created_at: datetime


class ApproveBody(BaseModel):
    slug: str = Field(pattern=SLUG)
    name: str | None = Field(default=None, max_length=120)
    gpu_limit: int = Field(ge=0, le=64)
    cpu_limit: float = Field(ge=0.5)
    memory_limit_mb: int = Field(ge=512)
    storage_quota_mb: int = Field(ge=1024)
    max_concurrent_jobs: int = Field(default=1, ge=1, le=32)
    members: list[MemberEmail] | None = None  # None → use the request's list
    review_note: str | None = None


class RejectBody(BaseModel):
    review_note: str = Field(min_length=1)
