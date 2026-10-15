from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from app.schemas.common import ORMModel
from app.schemas.user import UserRead

DataFormat = Literal["csv", "parquet", "image_folder", "coco", "yolo", "npy", "jsonl", "spectrum_csv"]


class DataSourceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    kind: Literal["minio", "url"]
    endpoint: str | None = None
    bucket: str | None = None
    object_path: str | None = None
    url: str | None = None
    access_key: str | None = None
    secret_key: str | None = None
    region: str | None = None
    headers: dict[str, str] | None = None
    format: DataFormat
    default_spec: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _check(self) -> DataSourceCreate:
        if self.kind == "minio" and not (self.endpoint and self.bucket and self.object_path):
            raise ValueError("minio 需要 endpoint、bucket、object_path")
        if self.kind == "url" and not self.url:
            raise ValueError("url 需要 url")
        return self


class DataSourceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    endpoint: str | None = None
    bucket: str | None = None
    object_path: str | None = None
    url: str | None = None
    access_key: str | None = None
    secret_key: str | None = None
    region: str | None = None
    headers: dict[str, str] | None = None
    format: DataFormat | None = None
    default_spec: dict[str, Any] | None = None


class DataSourceRead(ORMModel):
    id: int
    project_id: int
    name: str
    kind: str
    endpoint: str | None
    bucket: str | None
    object_path: str | None
    url: str | None
    has_credentials: bool = False
    format: str
    default_spec: dict[str, Any] | None
    last_check_ok: bool | None
    last_check_message: str | None
    last_checked_at: datetime | None
    created_by: UserRead
    created_at: datetime
