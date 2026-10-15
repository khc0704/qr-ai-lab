from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import bad_request, conflict, not_found
from app.db.base import utcnow
from app.models import Artifact, Job, Project, ProjectMember, User
from app.schemas.project import MemberAdd, MemberUpdate, ProjectUpdate, ProjectUsage, QuotaUpdate
from app.services import audit
from app.services import users as users_svc
from app.storage.local import get_storage


async def get_by_slug(session: AsyncSession, slug: str) -> Project:
    p = (await session.execute(select(Project).where(Project.slug == slug))).scalar_one_or_none()
    if p is None:
        raise not_found("PROJECT_NOT_FOUND", f"找不到專案 {slug}")
    return p


async def get(session: AsyncSession, project_id: int) -> Project:
    p = await session.get(Project, project_id)
    if p is None:
        raise not_found("PROJECT_NOT_FOUND", "找不到專案")
    return p


async def list_for_user(session: AsyncSession, user: User, include_archived: bool = False) -> list[Project]:
    stmt = select(Project)
    if not user.is_admin:
        stmt = stmt.join(ProjectMember, ProjectMember.project_id == Project.id).where(ProjectMember.user_id == user.id)
    if not include_archived:
        stmt = stmt.where(Project.status == "active")
    rows = (await session.execute(stmt.order_by(Project.created_at.desc()))).scalars().unique().all()
    return list(rows)


async def usage_map(session: AsyncSession, project_ids: list[int]) -> dict[int, ProjectUsage]:
    out = {pid: ProjectUsage() for pid in project_ids}
    if not project_ids:
        return out
    rows = (
        (
            await session.execute(
                select(Job).where(Job.project_id.in_(project_ids), Job.status.in_(("scheduled", "running")))
            )
        )
        .scalars()
        .all()
    )
    for j in rows:
        u = out[j.project_id]
        u.gpu += j.requested_gpu
        u.cpu += float(j.requested_cpu)
        u.memory_mb += j.requested_memory_mb
        u.running_jobs += 1
    return out


async def update(session: AsyncSession, actor: User, project: Project, body: ProjectUpdate) -> Project:
    if body.name is not None:
        project.name = body.name
    if body.description is not None:
        project.description = body.description
    await session.commit()
    return project


async def archive(session: AsyncSession, actor: User, project: Project) -> Project:
    active = (
        await session.execute(
            select(func.count())
            .select_from(Job)
            .where(Job.project_id == project.id, Job.status.in_(("queued", "scheduled", "running")))
        )
    ).scalar_one()
    if active:
        raise conflict("PROJECT_HAS_ACTIVE_JOBS", f"還有 {active} 個任務未結束，請先取消")
    project.status = "archived"
    project.archived_at = utcnow()
    await audit.record(session, actor.id, "project.archive", "project", project.id)
    await session.commit()
    return project


async def update_quota(session: AsyncSession, admin: User, project: Project, body: QuotaUpdate) -> Project:
    before = {k: getattr(project, k) for k in body.model_fields}
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(project, k, v)
    await audit.record(
        session,
        admin.id,
        "project.quota.update",
        "project",
        project.id,
        {
            "before": {k: float(v) if v is not None else None for k, v in before.items()},
            "after": body.model_dump(exclude_none=True),
        },
    )
    await session.commit()
    return project


async def add_member(session: AsyncSession, actor: User, project: Project, body: MemberAdd) -> Project:
    user = await users_svc.find_by_username_or_email(session, body.username_or_email)
    if user is None:
        raise not_found("USER_NOT_FOUND", "找不到使用者（對方必須先登入過一次）")
    if project.role_of(user.id):
        raise conflict("ALREADY_MEMBER", "已是成員")
    session.add(ProjectMember(project_id=project.id, user_id=user.id, role=body.role, added_by_id=actor.id))
    await audit.record(
        session, actor.id, "project.member.add", "project", project.id, {"user_id": user.id, "role": body.role}
    )
    await session.commit()
    return await get(session, project.id)


async def update_member(
    session: AsyncSession, actor: User, project: Project, user_id: int, body: MemberUpdate
) -> Project:
    m = next((m for m in project.members if m.user_id == user_id), None)
    if m is None:
        raise not_found("MEMBER_NOT_FOUND", "不是成員")
    if m.role == "owner":
        raise bad_request("OWNER_IMMUTABLE", "擁有者角色不能變更")
    m.role = body.role
    await audit.record(
        session, actor.id, "project.member.update", "project", project.id, {"user_id": user_id, "role": body.role}
    )
    await session.commit()
    return await get(session, project.id)


async def remove_member(session: AsyncSession, actor: User, project: Project, user_id: int) -> Project:
    m = next((m for m in project.members if m.user_id == user_id), None)
    if m is None:
        raise not_found("MEMBER_NOT_FOUND", "不是成員")
    if m.role == "owner":
        raise bad_request("OWNER_IMMUTABLE", "擁有者不能移除")
    await session.delete(m)
    await audit.record(session, actor.id, "project.member.remove", "project", project.id, {"user_id": user_id})
    await session.commit()
    return await get(session, project.id)


async def recompute_storage(session: AsyncSession, project: Project) -> int:
    used = get_storage().usage_bytes(f"projects/{project.slug}")
    project.storage_used_bytes = used
    await session.flush()
    return used


async def default_model(session: AsyncSession, project_id: int) -> Artifact | None:
    return (
        await session.execute(
            select(Artifact).where(
                Artifact.project_id == project_id, Artifact.kind == "model", Artifact.is_default.is_(True)
            )
        )
    ).scalar_one_or_none()
