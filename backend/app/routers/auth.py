from __future__ import annotations

from fastapi import APIRouter

from app.core.config import get_settings
from app.core.deps import CurrentUser, DbSession
from app.core.errors import unauthorized
from app.core.security import create_access_token
from app.schemas.common import Ok
from app.schemas.user import LoginBody, MeRead, TokenResponse, UserRead
from app.services import users as users_svc

router = APIRouter(tags=["auth"])


@router.post("/auth/login", response_model=TokenResponse, summary="本地帳號登入（Keycloak 接上前的過渡方案）")
async def login(body: LoginBody, session: DbSession) -> TokenResponse:
    s = get_settings()
    if s.auth_mode != "local":
        raise unauthorized("LOCAL_LOGIN_DISABLED", "請透過 Keycloak 登入")
    user = await users_svc.authenticate(session, body.username, body.password)
    if user is None:
        raise unauthorized("BAD_CREDENTIALS", "帳號或密碼錯誤")
    token = create_access_token(user_id=user.id, username=user.username, role=user.role, settings=s)
    return TokenResponse(access_token=token, expires_in=s.access_token_minutes * 60, user=UserRead.model_validate(user))


@router.post("/auth/logout", response_model=Ok, summary="登出（JWT 無狀態，前端清除 cookie 即可）")
async def logout(_: CurrentUser) -> Ok:
    return Ok()


@router.get("/me", response_model=MeRead, summary="目前使用者（含權限清單）")
async def me(user: CurrentUser) -> MeRead:
    out = MeRead.model_validate(user)
    out.permissions = user.permissions
    out.auth_mode = get_settings().auth_mode
    return out


@router.get("/auth/config", summary="登入方式（前端登入頁用，不需登入）")
async def auth_config() -> dict[str, str | bool]:
    s = get_settings()
    return {"mode": s.auth_mode, "keycloak": s.auth_mode == "keycloak", "issuer": s.keycloak_issuer or ""}
