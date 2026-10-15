from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel
from app.schemas.user import UserRead

ProjectRole = Literal["owner", "maintainer", "member", "viewer"]


class ProjectMemberRead(ORMModel):
    user: UserRead
    role: str
    created_at: datetime


class ProjectUsage(BaseModel):
    gpu: int = 0
    cpu: float = 0
    memory_mb: int = 0
    running_jobs: int = 0


class ProjectRead(ORMModel):
    id: int
    slug: str
    name: str
    description: str | None
    data_type: str
    task_type: str
    status: str
    owner: UserRead
    gpu_limit: int
    cpu_limit: float
    memory_limit_mb: int
    storage_quota_mb: int
    storage_used_bytes: int
    max_concurrent_jobs: int
    default_job_timeout_minutes: int | None
    members: list[ProjectMemberRead]
    usage: ProjectUsage = Field(default_factory=ProjectUsage)
    created_at: datetime
    approved_at: datetime | None
    archived_at: datetime | None


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = None


class QuotaUpdate(BaseModel):
    gpu_limit: int | None = Field(default=None, ge=0, le=64)
    cpu_limit: float | None = Field(default=None, ge=0.5)
    memory_limit_mb: int | None = Field(default=None, ge=512)
    storage_quota_mb: int | None = Field(default=None, ge=1024)
    max_concurrent_jobs: int | None = Field(default=None, ge=1, le=32)
    default_job_timeout_minutes: int | None = Field(default=None, ge=1)


class MemberAdd(BaseModel):
    username_or_email: str = Field(min_length=1)
    role: Literal["maintainer", "member", "viewer"] = "member"


class MemberUpdate(BaseModel):
    role: Literal["maintainer", "member", "viewer"]
