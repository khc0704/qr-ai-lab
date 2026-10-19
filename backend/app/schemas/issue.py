from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel
from app.schemas.user import UserRead

IssueType = Literal["question", "bug", "feature"]


class IssueCreate(BaseModel):
    type: IssueType
    title: str = Field(min_length=1, max_length=200)
    body: str = ""
    project_slug: str | None = None


class IssueUpdate(BaseModel):
    type: IssueType | None = None
    title: str | None = Field(default=None, min_length=1, max_length=200)
    body: str | None = None
    assignee_id: int | None = None
    project_slug: str | None = None


class IssueClose(BaseModel):
    resolution_note: str = Field(min_length=1)


class IssueRead(ORMModel):
    id: int
    type: str
    title: str
    body: str
    status: str
    author: UserRead
    assignee: UserRead | None
    project_slug: str | None = None
    resolution_note: str | None
    comment_count: int
    created_at: datetime
    updated_at: datetime
    closed_at: datetime | None


class CommentCreate(BaseModel):
    body: str = Field(min_length=1)


class CommentUpdate(BaseModel):
    body: str = Field(min_length=1)


class CommentRead(ORMModel):
    id: int
    target_type: str
    target_id: int
    author: UserRead | None
    kind: str
    body: str
    created_at: datetime
    # Equals created_at until the body is edited (the UI shows 「已編輯」 when it is later).
    updated_at: datetime
