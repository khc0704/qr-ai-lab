from __future__ import annotations

from datetime import datetime
from typing import Any

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
