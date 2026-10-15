from __future__ import annotations

from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

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


async def update_user(session: AsyncSession, actor: User, user: User, body: UserUpdate) -> User:
    before = {"role": user.role, "is_active": user.is_active}
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


async def upsert_keycloak_user(session: AsyncSession, claims: dict[str, Any]) -> User:
    sub = claims["sub"]
    roles = (claims.get("realm_access") or {}).get("roles") or []
    role = "admin" if "admin" in roles else "user"
    user = (await session.execute(select(User).where(User.keycloak_sub == sub))).scalar_one_or_none()
    if user is None:
        user = User(
            keycloak_sub=sub,
            auth_provider="keycloak",
            username=claims.get("preferred_username") or sub,
            email=claims.get("email") or "",
            display_name=claims.get("name"),
        )
        session.add(user)
    user.role = role
    user.email = claims.get("email") or user.email
    user.display_name = claims.get("name") or user.display_name
    user.last_login_at = utcnow()
    await session.commit()
    return user


async def seed_users(session: AsyncSession, admin_password: str, user_password: str) -> list[str]:
    """Interim accounts until Keycloak: `admin` and `user`. Idempotent."""
    created: list[str] = []
    for username, password, role, name, email in (
        ("admin", admin_password, "admin", "管理員", "admin@example.com"),
        ("user", user_password, "user", "一般使用者", "user@example.com"),
    ):
        if await get_by_username(session, username) is None:
            await create_local_user(
                session, username=username, password=password, email=email, display_name=name, role=role
            )
            created.append(username)
    return created
