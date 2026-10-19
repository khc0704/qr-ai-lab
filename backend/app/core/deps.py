"""FastAPI dependencies: DB session, current user, admin, project role, internal job token."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Path
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import conflict, forbidden, not_found, unauthorized
from app.core.permissions import PERMISSIONS
from app.core.security import decode_access_token, decode_job_token, decode_keycloak_token
from app.db.session import get_session
from app.models import Job, Project, User

bearer = HTTPBearer(auto_error=False)
DbSession = Annotated[AsyncSession, Depends(get_session)]
Creds = Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]

ROLE_ORDER = {"viewer": 0, "member": 1, "maintainer": 2, "owner": 3}


async def get_current_user(session: DbSession, creds: Creds) -> User:
    if creds is None or not creds.credentials:
        raise unauthorized()
    s = get_settings()
    if s.auth_mode == "keycloak":
        from app.services import users as users_svc

        claims = await asyncio.to_thread(decode_keycloak_token, creds.credentials, s)  # JWKS fetch is blocking
        user = await users_svc.upsert_keycloak_user(session, claims)
    else:
        claims = decode_access_token(creds.credentials, s)
        user = await session.get(User, int(claims["sub"]))
    if user is None or not user.is_active:
        raise unauthorized("USER_INACTIVE", "帳號不存在或已停用")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def require_admin(user: CurrentUser) -> User:
    """admin or superadmin (read-only admin area, day-to-day operations)."""
    if not user.is_admin:
        raise forbidden("ADMIN_ONLY", "只有管理員可以執行")
    return user


AdminUser = Annotated[User, Depends(require_admin)]


def require_perm(perm: str):
    """Dependency factory: the current user must hold ``perm`` (see ``app.core.permissions``)."""
    if perm not in PERMISSIONS:
        raise KeyError(perm)

    async def dep(user: CurrentUser) -> User:
        if not user.has_perm(perm):
            raise forbidden("PERMISSION_DENIED", f"需要 {perm} 權限（{'、'.join(sorted(PERMISSIONS[perm]))}）")
        return user

    dep.__name__ = f"require_{perm.replace('.', '_')}"
    return dep


SuperAdminUser = Annotated[User, Depends(require_perm("users.manage"))]


@dataclass
class ProjectAccess:
    project: Project
    role: str  # effective role; admins are owners everywhere
    user: User


def project_access(min_role: str = "viewer", *, active: bool = False):
    """``active=True``: the route changes the project's work (data sources, uploads, jobs, members) and is only
    allowed while the project is 進行中; pending / completed / archived projects stay readable."""

    async def dep(session: DbSession, user: CurrentUser, slug: Annotated[str, Path()]) -> ProjectAccess:
        project = (await session.execute(select(Project).where(Project.slug == slug))).scalar_one_or_none()
        if project is None:
            raise not_found("PROJECT_NOT_FOUND", f"找不到專案 {slug}")
        role = "owner" if user.is_admin else project.role_of(user.id)
        if role is None:
            raise not_found("PROJECT_NOT_FOUND", f"找不到專案 {slug}")  # hide existence from non-members
        if ROLE_ORDER[role] < ROLE_ORDER[min_role]:
            raise forbidden("PROJECT_ROLE", f"需要 {min_role} 以上的專案角色")
        if active and project.status != "active":
            raise conflict("PROJECT_NOT_ACTIVE", f"專案狀態是 {project.status}，核准並進行中的專案才能操作")
        return ProjectAccess(project=project, role=role, user=user)

    dep.__name__ = f"project_access_{min_role}{'_active' if active else ''}"
    return dep


async def get_internal_job(session: DbSession, creds: Creds, job_id: Annotated[int, Path()]) -> Job:
    """Trainer → backend calls carry a per-job token whose subject must match the path."""
    if creds is None:
        raise unauthorized("INVALID_JOB_TOKEN", "缺少 job token")
    claims = decode_job_token(creds.credentials)
    if int(claims["sub"]) != job_id:
        raise forbidden("JOB_TOKEN_MISMATCH", "token 不屬於此 job")
    job = await session.get(Job, job_id)
    if job is None:
        raise not_found("JOB_NOT_FOUND", "找不到 job")
    return job


InternalJob = Annotated[Job, Depends(get_internal_job)]


async def get_live_internal_job(job: InternalJob) -> Job:
    """Writes (status / metrics / artifacts / result) are accepted only while the job is scheduled or running:
    the token outlives the process by design (timeout + grace), a finished or cancelled job must stay as it is."""
    if job.status not in ("scheduled", "running"):
        raise conflict("JOB_FINISHED", f"任務已結束（{job.status}），不再接受回報")
    return job


LiveInternalJob = Annotated[Job, Depends(get_live_internal_job)]
