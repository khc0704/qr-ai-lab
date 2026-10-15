from __future__ import annotations

import re

from sqlalchemy import delete as sql_delete
from sqlalchemy import func, select
from sqlalchemy import update as sql_update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import bad_request, conflict, not_found
from app.db.base import utcnow
from app.models import Artifact, DataSource, Issue, Job, Project, ProjectMember, ProjectRequest, Upload, User
from app.schemas.project import MemberAdd, MemberUpdate, ProjectUpdate, ProjectUsage, QuotaUpdate
from app.services import audit
from app.services import settings as settings_svc
from app.services import users as users_svc
from app.storage.local import get_storage

PERSONAL_PREFIX = "ws-"


def personal_slug(username: str) -> str:
    base = re.sub(r"[^a-z0-9-]+", "-", username.lower()).strip("-") or "user"
    return (PERSONAL_PREFIX + base)[:60]


async def personal(session: AsyncSession, user: User) -> Project:
    """The user's personal workspace: created on first use with the admin's ToolDefaults quota. It hosts the
    preprocessing / analysis tool jobs so they go through the same queue, limits, logs and cleanup as any job."""
    p = (
        await session.execute(select(Project).where(Project.owner_id == user.id, Project.kind == "personal"))
    ).scalar_one_or_none()
    if p is not None:
        return p
    d = await settings_svc.get_tool_defaults(session)
    slug = personal_slug(user.username)
    if (await session.execute(select(Project).where(Project.slug == slug))).scalar_one_or_none():
        slug = f"{slug}-{user.id}"
    p = Project(
        slug=slug,
        name=f"個人工作區（{user.display_name or user.username}）",
        description="資料前處理與資料分析服務的任務在這裡排隊執行；配額由管理員的「工具預設」決定，可在專案配額頁調整。",
        data_type="TABULAR",
        task_type="classification",
        kind="personal",
        owner_id=user.id,
        gpu_limit=d.gpu_limit,
        cpu_limit=d.cpu_limit,
        memory_limit_mb=d.memory_limit_mb,
        storage_quota_mb=d.storage_quota_mb,
        max_concurrent_jobs=d.max_concurrent_jobs,
        approved_at=utcnow(),
    )
    session.add(p)
    await session.flush()
    session.add(ProjectMember(project_id=p.id, user_id=user.id, role="owner", added_by_id=user.id))
    get_storage().ensure(get_storage().project_dir(p.slug))
    await audit.record(session, user.id, "project.personal.create", "project", p.id, {"slug": p.slug})
    await session.commit()
    # commit expired the instance: reload it with its eager relationships (members, owner) for the serializer
    return (
        await session.execute(select(Project).where(Project.id == p.id).execution_options(populate_existing=True))
    ).scalar_one()


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


async def list_for_user(
    session: AsyncSession, user: User, include_archived: bool = False, include_personal: bool = False
) -> list[Project]:
    stmt = select(Project)
    if not user.is_admin:
        stmt = stmt.join(ProjectMember, ProjectMember.project_id == Project.id).where(ProjectMember.user_id == user.id)
    if not include_archived:
        stmt = stmt.where(Project.status == "active")
    if not include_personal:
        stmt = stmt.where(Project.kind == "standard")
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


async def delete(session: AsyncSession, actor: User, project: Project) -> None:
    """superadmin: remove the project, its jobs, artifacts, data-source references, members and the folder on disk.
    Refused while any job is still queued / scheduled / running. Discussion threads and the original request keep
    their rows but lose the link (history stays readable)."""
    active = (
        await session.execute(
            select(func.count())
            .select_from(Job)
            .where(Job.project_id == project.id, Job.status.in_(("queued", "scheduled", "running")))
        )
    ).scalar_one()
    if active:
        raise conflict("PROJECT_HAS_ACTIVE_JOBS", f"還有 {active} 個任務未結束，請先中斷")
    counts = {
        "jobs": (
            await session.execute(select(func.count()).select_from(Job).where(Job.project_id == project.id))
        ).scalar_one(),
        "artifacts": (
            await session.execute(select(func.count()).select_from(Artifact).where(Artifact.project_id == project.id))
        ).scalar_one(),
    }
    # FK order: jobs → artifacts (inference jobs) and artifacts → jobs (RESTRICT both ways), so break the link first.
    await session.execute(sql_update(Job).where(Job.project_id == project.id).values(artifact_id=None))
    await session.execute(sql_delete(Artifact).where(Artifact.project_id == project.id))
    await session.execute(sql_delete(Upload).where(Upload.project_id == project.id))
    await session.execute(sql_delete(Job).where(Job.project_id == project.id))
    await session.execute(sql_delete(DataSource).where(DataSource.project_id == project.id))
    await session.execute(sql_update(Issue).where(Issue.project_id == project.id).values(project_id=None))
    await session.execute(
        sql_update(ProjectRequest).where(ProjectRequest.project_id == project.id).values(project_id=None)
    )
    await audit.record(
        session,
        actor.id,
        "project.delete",
        "project",
        project.id,
        {"slug": project.slug, "name": project.name, **counts},
    )
    await session.delete(project)  # members cascade
    await session.flush()
    storage = get_storage()
    storage.remove_tree(f"projects/{project.slug}")
    storage.remove_tree(f"uploads/{project.id}")
    await session.commit()


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
