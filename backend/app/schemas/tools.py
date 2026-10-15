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
    name: str | None = Field(default=None, max_length=120)


class ToolPreviewBody(ToolProcessBody):
    sample: int = Field(default=5, ge=1, le=50)


class ToolAnalyzeBody(BaseModel):
    """Start an analysis job on a tool upload. tabular_profile: correlations, collinearity (VIF), relevance to the
    target, recommendations. image_quality: IQA metrics per image, drift across groups (folders), embeddings."""

    analysis: Literal["tabular_profile", "image_quality"]
    params: dict[str, Any] = Field(default_factory=dict)
    name: str | None = Field(default=None, max_length=120)
