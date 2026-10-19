from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class UploadRead(ORMModel):
    id: int
    project_id: int
    original_filename: str
    size_bytes: int
    format: str
    detected_spec: dict[str, Any] | None
    status: str
    expires_at: datetime
    created_at: datetime


class PreprocessPreviewBody(BaseModel):
    """Try preprocessing steps on a sample of an upload (nothing is stored)."""

    steps: list[dict[str, Any]] = Field(default_factory=list, max_length=20)
    sample: int = Field(default=5, ge=1, le=500)
    spec: dict[str, Any] = Field(default_factory=dict)  # target / text_column / layout … as the job would use
    task_type: str | None = None
    thumb: int = Field(default=256, ge=64, le=1024)  # IMAGE: longest side of the preview thumbnails
    image_ids: list[str] | None = Field(default=None, max_length=16)  # IMAGE: only these entries (lightbox)
