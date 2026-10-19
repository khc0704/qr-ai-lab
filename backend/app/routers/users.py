from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.core.deps import CurrentUser, DbSession, require_perm
from app.core.errors import not_found
from app.models import User
from app.schemas.common import Page
from app.schemas.user import UserLookup, UserRead, UserUpdate
from app.services import users as users_svc

router = APIRouter(prefix="/users", tags=["users"])
UserViewer = Annotated[User, Depends(require_perm("users.view"))]
UserManager = Annotated[User, Depends(require_perm("users.manage"))]


@router.get("", response_model=Page[UserRead], summary="使用者列表（admin）")
async def list_users(
    session: DbSession,
    _: UserViewer,
    q: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
) -> Page[UserRead]:
    rows, total = await users_svc.list_users(session, q, page, page_size)
    return Page(items=[UserRead.model_validate(u) for u in rows], total=total, page=page, page_size=page_size)


# Declared before any `/{user_id}` route so the literal path is never captured by the parameter.
@router.get("/lookup", response_model=list[UserLookup], status_code=200, summary="使用者自動完成（所有登入者）")
async def lookup_users(
    session: DbSession,
    _: CurrentUser,
    q: str = Query("", max_length=100, description="至少 2 個字；比對帳號、顯示名稱、email（不分大小寫）"),
) -> list[UserLookup]:
    """Autocomplete for member / applicant pickers: identity fields only (no role, no hash), active users,
    at most 10 rows ordered by username; fewer than 2 characters returns an empty list."""
    return [UserLookup.model_validate(u) for u in await users_svc.lookup_users(session, q)]


@router.patch(
    "/{user_id}",
    response_model=UserRead,
    summary="改系統角色（admin / user）或啟用（superadmin；superadmin 本身由 SUPERADMIN_USERNAME 固定）",
)
async def update_user(user_id: int, body: UserUpdate, session: DbSession, admin: UserManager) -> UserRead:
    user = await users_svc.get_by_id(session, user_id)
    if user is None:
        raise not_found("USER_NOT_FOUND", "找不到使用者")
    return UserRead.model_validate(await users_svc.update_user(session, admin, user, body))
