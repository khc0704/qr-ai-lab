from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import bad_request, conflict, forbidden
from app.core.permissions import highest_role
from app.core.security import hash_password, verify_password
from app.db.base import utcnow
from app.models import User
from app.schemas.user import UserUpdate
from app.services import audit

SUPERADMIN_FIXED_MESSAGE = "superadmin 只有一位，由環境變數 SUPERADMIN_USERNAME 指定，不能在這裡指派、降級或停用"


def configured_superadmin() -> str:
    """The one username that holds role superadmin (SUPERADMIN_USERNAME); empty = nobody."""
    return get_settings().superadmin_username


def is_configured_superadmin(username: str) -> bool:
    name = configured_superadmin()
    return bool(name) and username == name


def apply_superadmin_rule(user: User) -> bool:
    """Exactly one superadmin: the configured username always carries the role, any other row that still has it is
    demoted to admin. Applied at every login / upsert and at startup. Returns True when the row changed."""
    if is_configured_superadmin(user.username):
        expected = "superadmin"
    elif user.role == "superadmin":
        expected = "admin"
    else:
        return False
    if user.role == expected:
        return False
    user.role = expected
    return True


async def ensure_single_superadmin(session: AsyncSession) -> dict[str, list[str]]:
    """Startup / seed: reconcile every row at once (SUPERADMIN_USERNAME may have changed between restarts, or a row
    may have been edited by hand). Returns the usernames promoted / demoted."""
    name = configured_superadmin()
    cond = or_(User.role == "superadmin", User.username == name) if name else User.role == "superadmin"
    changed: dict[str, list[str]] = {"promoted": [], "demoted": []}
    for u in (await session.execute(select(User).where(cond).order_by(User.id))).scalars():
        if apply_superadmin_rule(u):
            changed["promoted" if u.role == "superadmin" else "demoted"].append(u.username)
    await session.commit()
    return changed


async def get_by_id(session: AsyncSession, user_id: int) -> User | None:
    return await session.get(User, user_id)


async def get_by_username(session: AsyncSession, username: str) -> User | None:
    return (await session.execute(select(User).where(User.username == username))).scalar_one_or_none()


async def find_by_username_or_email(session: AsyncSession, value: str) -> User | None:
    """Exact username first; otherwise the e-mail, which is not unique (Keycloak and local accounts may share
    one), so an ambiguous e-mail is an error instead of a 500."""
    rows = list((await session.execute(select(User).where(or_(User.username == value, User.email == value)))).scalars())
    by_name = [u for u in rows if u.username == value]
    if by_name:
        return by_name[0]
    if len(rows) > 1:
        raise conflict("AMBIGUOUS_USER", f"有 {len(rows)} 個帳號使用 {value}，請改用帳號名稱")
    return rows[0] if rows else None


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


LOOKUP_MIN_CHARS = 2
LOOKUP_LIMIT = 10


async def lookup_users(session: AsyncSession, q: str | None, limit: int = LOOKUP_LIMIT) -> list[User]:
    """Autocomplete for pickers, callable by every logged-in user: case-insensitive contains-match on username /
    display name / e-mail, active accounts only, at most `limit` rows ordered by username. Too short a query
    (< LOOKUP_MIN_CHARS) returns nothing so the directory cannot be enumerated with "a", "b", …"""
    term = (q or "").strip()
    if len(term) < LOOKUP_MIN_CHARS:
        return []
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    like = f"%{escaped}%"
    stmt = (
        select(User)
        .where(
            User.is_active.is_(True),
            or_(
                User.username.ilike(like, escape="\\"),
                User.display_name.ilike(like, escape="\\"),
                User.email.ilike(like, escape="\\"),
            ),
        )
        .order_by(User.username)
        .limit(limit)
    )
    return list((await session.execute(stmt)).scalars().all())


async def authenticate(session: AsyncSession, username: str, password: str) -> User | None:
    user = await get_by_username(session, username)
    if user is None or not user.is_active or user.auth_provider != "local":
        return None
    if not await asyncio.to_thread(verify_password, password, user.password_hash):  # argon2 ~50 ms CPU
        return None
    user.last_login_at = utcnow()
    apply_superadmin_rule(user)
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


async def update_user(session: AsyncSession, actor: User, user: User, body: UserUpdate) -> User:
    """Role / activation changes (superadmin only). The UI assigns at most admin: superadmin is exactly one account
    fixed by SUPERADMIN_USERNAME, which can neither be granted here nor demoted / deactivated."""
    before = {"role": user.role, "is_active": user.is_active}
    if not actor.is_superadmin and (body.role is not None or body.is_active is not None):
        raise forbidden("PERMISSION_DENIED", "只有 superadmin 可以調整角色或停用帳號")
    if body.role == "superadmin":
        raise bad_request("SUPERADMIN_FIXED", SUPERADMIN_FIXED_MESSAGE)
    if is_configured_superadmin(user.username) and (body.role is not None or body.is_active is False):
        raise bad_request("SUPERADMIN_FIXED", SUPERADMIN_FIXED_MESSAGE)
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
    """System role implied by the login: the configured superadmin, else the KEYCLOAK_ROLE_MAP match (opt-in, capped
    at admin). None = nothing mapped → keep whatever /admin/users set; with the default empty map Keycloak only
    supplies identity."""
    s = get_settings()
    if is_configured_superadmin(username):
        return "superadmin"
    mapped = highest_role([s.role_map[r] for r in keycloak_roles(claims, s.keycloak_client_id) if r in s.role_map])
    return "admin" if mapped == "superadmin" else mapped


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
            # The matching name only proves the name: privileges come from our own tables (granted again in
            # /admin/users after this first login) or from SUPERADMIN_USERNAME, never from the Keycloak account.
            user.role = "user"
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
    if mapped is not None and mapped != user.role:
        user.role = mapped
    apply_superadmin_rule(user)  # a stray superadmin row (not the configured name) is demoted here
    user.email = claims.get("email") or user.email
    user.display_name = (claims.get("name") or user.display_name or "")[:100] or None
    user.last_login_at = utcnow()
    try:
        await session.commit()
    except IntegrityError:
        # The first page after login fires parallel requests; another one just inserted this user.
        await session.rollback()
        stmt = select(User).where(User.keycloak_sub == sub).execution_options(populate_existing=True)
        user = (await session.execute(stmt)).scalar_one_or_none()
        if user is None:
            raise
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
            "superadmin" if is_configured_superadmin("superadmin") else "admin",
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
