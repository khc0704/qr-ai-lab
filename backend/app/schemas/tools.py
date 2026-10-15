from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

DataType = Literal["TABULAR", "IMAGE", "SEQUENCE", "TEXT", "SPECTRUM"]


class ToolUploadRead(BaseModel):
    """A file in the standalone preprocessing tool: lives under DATA_ROOT/tools/<id>/ until downloaded or expired.
    Nothing about it is written to the database."""

    id: str
    data_type: DataType
    original_filename: str
    size_bytes: int
    format: str
    detected_spec: dict[str, Any] | None = None
    expires_at: datetime
    created_at: datetime


class ToolProcessBody(BaseModel):
    steps: list[dict[str, Any]] = Field(default_factory=list, max_length=20)
    spec: dict[str, Any] = Field(default_factory=dict)
    task_type: str | None = None


class ToolPreviewBody(ToolProcessBody):
    sample: int = Field(default=5, ge=1, le=50)


class ToolProcessResult(BaseModel):
    id: str
    summary: dict[str, Any]
    zip_size_bytes: int
    download_path: str  # /tools/uploads/{id}/download — the file is deleted right after the download
