from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class UserRead(ORMModel):
    id: int
    username: str
    email: str
    display_name: str | None
    role: str
    is_active: bool
    auth_provider: str
    last_login_at: datetime | None = None


class MeRead(UserRead):
    """`/me`: the user plus the resolved permission list (frontend hides UI from it; the backend still decides)."""

    permissions: list[str] = []
    auth_mode: str = "local"


class UserUpdate(BaseModel):
    role: Literal["superadmin", "admin", "user"] | None = None
    is_active: bool | None = None
    display_name: str | None = None


class LoginBody(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=200)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserRead
