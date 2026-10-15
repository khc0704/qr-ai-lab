from __future__ import annotations

from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import bad_request, conflict, forbidden
from app.core.permissions import ROLE_RANK, highest_role
from app.core.security import hash_password, verify_password
from app.db.base import utcnow
from app.models import User
from app.schemas.user import UserUpdate
from app.services import audit


async def get_by_id(session: AsyncSession, user_id: int) -> User | None:
    return await session.get(User, user_id)


async def get_by_username(session: AsyncSession, username: str) -> User | None:
    return (await session.execute(select(User).where(User.username == username))).scalar_one_or_none()


async def find_by_username_or_email(session: AsyncSession, value: str) -> User | None:
    return (
        await session.execute(select(User).where(or_(User.username == value, User.email == value)))
    ).scalar_one_or_none()


async def list_users(
    session: AsyncSession, q: str | None = None, page: int = 1, page_size: int = 50
) -> tuple[list[User], int]:
    stmt = select(User)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(User.username.like(like), User.email.like(like), User.display_name.like(like)))
    total = (await session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (
        (await session.execute(stmt.order_by(User.id).offset((page - 1) * page_size).limit(page_size))).scalars().all()
    )
    return list(rows), total


async def authenticate(session: AsyncSession, username: str, password: str) -> User | None:
    user = await get_by_username(session, username)
    if user is None or not user.is_active or user.auth_provider != "local":
        return None
    if not verify_password(password, user.password_hash):
        return None
    user.last_login_at = utcnow()
    await session.commit()
    return user


async def create_local_user(
    session: AsyncSession, *, username: str, password: str, email: str, display_name: str | None, role: str = "user"
) -> User:
    user = User(
        username=username,
        email=email,
        display_name=display_name,
        role=role,
        auth_provider="local",
        password_hash=hash_password(password),
    )
    session.add(user)
    await session.commit()
    return user


async def count_superadmins(session: AsyncSession, *, active_only: bool = True) -> int:
    stmt = select(func.count()).select_from(User).where(User.role == "superadmin")
    if active_only:
        stmt = stmt.where(User.is_active.is_(True))
    return (await session.execute(stmt)).scalar_one()


async def update_user(session: AsyncSession, actor: User, user: User, body: UserUpdate) -> User:
    """Role / activation changes (superadmin only). Guards: never lock yourself out, never remove the last
    active superadmin, bootstrap usernames from SUPERADMIN_USERNAMES stay superadmin."""
    before = {"role": user.role, "is_active": user.is_active}
    if not actor.is_superadmin and (body.role is not None or body.is_active is not None):
        raise forbidden("PERMISSION_DENIED", "只有 superadmin 可以調整角色或停用帳號")
    losing_superadmin = user.role == "superadmin" and (
        (body.role is not None and body.role != "superadmin") or body.is_active is False
    )
    if losing_superadmin:
        if user.id == actor.id:
            raise bad_request("SELF_DEMOTE", "不能降級或停用自己的 superadmin 帳號")
        if await count_superadmins(session) <= 1:
            raise conflict("LAST_SUPERADMIN", "至少要保留一位啟用中的 superadmin")
        if user.username in get_settings().superadmin_usernames:
            raise bad_request("BOOTSTRAP_SUPERADMIN", "此帳號列在 SUPERADMIN_USERNAMES，請先從環境變數移除")
    if body.is_active is False and user.id == actor.id:
        raise bad_request("SELF_DEACTIVATE", "不能停用自己的帳號")
    if body.role is not None:
        user.role = body.role
    if body.is_active is not None:
        user.is_active = body.is_active
    if body.display_name is not None:
        user.display_name = body.display_name
    await audit.record(
        session,
        actor.id,
        "user.update",
        "user",
        user.id,
        {"before": before, "after": body.model_dump(exclude_none=True)},
    )
    await session.commit()
    return user


def keycloak_roles(claims: dict[str, Any], client_id: str | None = None) -> list[str]:
    """Realm roles plus the client roles of our own client (both are optional in a Keycloak access token)."""
    roles = list((claims.get("realm_access") or {}).get("roles") or [])
    if client_id:
        roles += list(((claims.get("resource_access") or {}).get(client_id) or {}).get("roles") or [])
    return roles


def role_from_claims(claims: dict[str, Any], username: str) -> str | None:
    """System role implied by the token (None = nothing mapped → keep whatever the UI set)."""
    s = get_settings()
    if username in s.superadmin_usernames:
        return "superadmin"
    mapped = [s.role_map[r] for r in keycloak_roles(claims, s.keycloak_client_id) if r in s.role_map]
    return highest_role(mapped)


async def upsert_keycloak_user(session: AsyncSession, claims: dict[str, Any]) -> User:
    sub = claims["sub"]
    username = claims.get("preferred_username") or sub
    user = (await session.execute(select(User).where(User.keycloak_sub == sub))).scalar_one_or_none()
    if user is None:
        # A local account with the same username (pre-created by an admin, or the seeded accounts during the
        # switch-over) is adopted instead of creating a second user with a suffixed name.
        existing = await get_by_username(session, username)
        if existing is not None and existing.keycloak_sub is None:
            user = existing
            user.keycloak_sub = sub
            user.auth_provider = "keycloak"
            user.password_hash = None
        else:
            user = User(
                keycloak_sub=sub,
                auth_provider="keycloak",
                username=username if existing is None else f"{username}-{sub[:8]}",
                email=claims.get("email") or "",
                display_name=claims.get("name"),
            )
            session.add(user)
    mapped = role_from_claims(claims, username)
    if mapped is not None and ROLE_RANK.get(mapped, -1) != ROLE_RANK.get(user.role, -1):
        user.role = mapped
    user.email = claims.get("email") or user.email
    user.display_name = claims.get("name") or user.display_name
    user.last_login_at = utcnow()
    await session.commit()
    return user


async def seed_users(
    session: AsyncSession, admin_password: str, user_password: str, superadmin_password: str | None = None
) -> list[str]:
    """Local accounts for dev / the interim period before Keycloak: `superadmin`, `admin`, `user`. Idempotent."""
    created: list[str] = []
    for username, password, role, name, email in (
        (
            "superadmin",
            superadmin_password or get_settings().seed_superadmin_password,
            "superadmin",
            "系統管理員",
            "superadmin@example.com",
        ),
        ("admin", admin_password, "admin", "管理員", "admin@example.com"),
        ("user", user_password, "user", "一般使用者", "user@example.com"),
    ):
        if await get_by_username(session, username) is None:
            await create_local_user(
                session, username=username, password=password, email=email, display_name=name, role=role
            )
            created.append(username)
    return created
