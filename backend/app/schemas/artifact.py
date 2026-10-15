from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class ArtifactRead(ORMModel):
    id: int
    project_id: int
    job_id: int
    name: str
    version: int
    kind: str
    model_family: str
    framework: str
    path: str
    size_bytes: int
    metrics: dict[str, Any] | None
    metadata: dict[str, Any] | None = Field(default=None, validation_alias="metadata_")
    is_default: bool
    created_at: datetime


class ArtifactUpdate(BaseModel):
    is_default: bool
