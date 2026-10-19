from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.schemas.common import ORMModel
from app.schemas.user import UserRead

ProjectRole = Literal["owner", "maintainer", "member", "viewer"]
DataType = Literal["TABULAR", "IMAGE", "SEQUENCE", "TEXT", "SPECTRUM"]
TaskType = Literal["classification", "regression", "detection", "segmentation", "anomaly_detection"]
DataScale = Literal["tiny", "small", "medium", "large"]
MemberRole = Literal["maintainer", "member", "viewer"]
SLUG = r"^[a-z0-9][a-z0-9-]{1,62}$"
# pending → in_review → active → completed; pending / in_review → rejected (editable, resubmit → pending);
# active / completed → archived. shared = the tool pool (preprocess / analysis jobs), never applied for.
PROJECT_STATUSES = ("pending", "in_review", "active", "rejected", "completed", "archived")
PENDING_STATUSES = ("pending", "in_review")


class MemberEmail(BaseModel):
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    role: MemberRole = "member"


class ApplicationRead(ORMModel):
    """The application that created the project (project_requests row), shown in the project's 申請 tab."""

    id: int
    purpose: str
    data_scale: str
    data_description: str | None
    requested_gpu: int
    requested_cpu: float
    requested_memory_mb: int
    requested_storage_mb: int
    members: list[MemberEmail] | None
    reviewer: UserRead | None
    review_note: str | None
    reviewed_at: datetime | None
    submitted_at: datetime
    comment_count: int


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
    kind: str = "standard"
    owner: UserRead
    application: ApplicationRead | None = None
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
    completed_at: datetime | None = None


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
    """Either `user_id` (from the autocomplete picker) or the legacy `username_or_email`; one is required."""

    user_id: int | None = Field(default=None, ge=1)
    username_or_email: str | None = Field(default=None, min_length=1, max_length=255)
    role: Literal["maintainer", "member", "viewer"] = "member"

    @model_validator(mode="after")
    def _one_identifier(self) -> MemberAdd:
        if self.user_id is None and not (self.username_or_email or "").strip():
            raise ValueError("user_id or username_or_email is required")
        return self


class MemberUpdate(BaseModel):
    role: Literal["maintainer", "member", "viewer"]


class ProjectApplyBody(BaseModel):
    """Submitting an application creates the project in status `pending`."""

    title: str = Field(min_length=1, max_length=200)
    purpose: str = Field(min_length=1)
    data_type: DataType
    task_type: TaskType
    data_scale: DataScale
    data_description: str | None = None
    requested_gpu: int = Field(default=0, ge=0, le=64)
    requested_cpu: float = Field(default=2, ge=0.5, le=999)
    requested_memory_mb: int = Field(default=4096, ge=512)
    requested_storage_mb: int = Field(default=10240, ge=1024)
    proposed_slug: str | None = Field(default=None, pattern=SLUG)
    members: list[MemberEmail] = Field(default_factory=list)


class ApplicationUpdate(BaseModel):
    """Applicant edits while pending / rejected (a rejected application goes back to pending)."""

    title: str | None = Field(default=None, min_length=1, max_length=200)
    purpose: str | None = None
    data_type: DataType | None = None
    task_type: TaskType | None = None
    data_scale: DataScale | None = None
    data_description: str | None = None
    requested_gpu: int | None = Field(default=None, ge=0, le=64)
    requested_cpu: float | None = Field(default=None, ge=0.5, le=999)
    requested_memory_mb: int | None = Field(default=None, ge=512)
    requested_storage_mb: int | None = Field(default=None, ge=1024)
    members: list[MemberEmail] | None = None


class ApproveBody(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    gpu_limit: int = Field(ge=0, le=64)
    cpu_limit: float = Field(ge=0.5)
    memory_limit_mb: int = Field(ge=512)
    storage_quota_mb: int = Field(ge=1024)
    max_concurrent_jobs: int = Field(default=1, ge=1, le=32)
    members: list[MemberEmail] | None = None  # None → use the application's list
    review_note: str | None = None


class RejectBody(BaseModel):
    review_note: str = Field(min_length=1)
