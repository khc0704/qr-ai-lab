from __future__ import annotations

from fastapi import APIRouter, Query

from app.core.deps import AdminUser, DbSession
from app.core.errors import not_found
from app.schemas.common import Page
from app.schemas.user import UserRead, UserUpdate
from app.services import users as users_svc

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=Page[UserRead], summary="使用者列表（admin）")
async def list_users(
    session: DbSession,
    _: AdminUser,
    q: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
) -> Page[UserRead]:
    rows, total = await users_svc.list_users(session, q, page, page_size)
    return Page(items=[UserRead.model_validate(u) for u in rows], total=total, page=page, page_size=page_size)


@router.patch("/{user_id}", response_model=UserRead, summary="改系統角色 / 啟用（admin）")
async def update_user(user_id: int, body: UserUpdate, session: DbSession, admin: AdminUser) -> UserRead:
    user = await users_svc.get_by_id(session, user_id)
    if user is None:
        raise not_found("USER_NOT_FOUND", "找不到使用者")
    return UserRead.model_validate(await users_svc.update_user(session, admin, user, body))
