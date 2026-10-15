from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ArtifactRef(BaseModel):
    id: int
    name: str
    version: int
    model_family: str
    framework: str
    file: str  # file name inside the mounted model dir (JOB_MODEL_DIR, default /job/model)
    metadata: dict[str, Any] | None = None


class JobSpec(BaseModel):
    job_id: int
    kind: str
    project_slug: str
    data_type: str
    task_type: str | None
    mode: str | None
    model_family: str | None
    config: dict[str, Any]
    input: dict[str, Any]
    artifact: ArtifactRef | None = None
    resources: dict[str, Any]
    timeout_minutes: int
    families: dict[str, Any] = Field(
        default_factory=dict
    )  # catalog entries (defaults, search_space, framework) the job may use
    zoo_weights: dict[str, str] = Field(default_factory=dict)  # weight id → file name under MODEL_ZOO_ROOT


class StatusBody(BaseModel):
    status: Literal["running", "succeeded", "failed"] | None = None
    progress: float | None = Field(default=None, ge=0, le=100)
    stage: str | None = None
    message: str | None = None


class MetricsBody(BaseModel):
    epoch: int | None = None
    trial: int | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)
    leaderboard_row: dict[str, Any] | None = None


class ArtifactRegister(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    kind: Literal["model", "weights", "preprocessor", "report", "metrics"]
    path: str = Field(min_length=1)  # relative to the job output dir
    framework: str = Field(min_length=1, max_length=32)
    metrics: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None
    set_default: bool = False


class ResultBody(BaseModel):
    result: dict[str, Any] | None = None
    output_path: str | None = None  # relative to the job output dir
