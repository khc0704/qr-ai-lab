from __future__ import annotations

import asyncio

from sqlalchemy import delete as sql_delete
from sqlalchemy import func, select
from sqlalchemy import update as sql_update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import bad_request, conflict, not_found
from app.db.base import utcnow
from app.models import Artifact, Comment, DataSource, Issue, Job, Project, ProjectMember, ProjectRequest, Upload, User
from app.schemas.project import MemberAdd, MemberUpdate, ProjectUpdate, ProjectUsage, QuotaUpdate
from app.services import audit
from app.services import settings as settings_svc
from app.services import users as users_svc
from app.storage.local import get_storage

SHARED_SLUG = "tools"
_shared_lock = asyncio.Lock()


async def shared(session: AsyncSession, user: User) -> Project:
    """The tool pool: one system project (kind=shared) that hosts every preprocessing / analysis job, so they go
    through the same queue, limits, logs and cleanup as any job. Its quota is the admin's ToolPool setting. Created
    on first use; nobody is a member (tool jobs are visible to their creator and to admins only)."""
    stmt = select(Project).where(Project.kind == "shared")
    p = (await session.execute(stmt)).scalar_one_or_none()
    if p is not None:
        return p
    async with _shared_lock:
        p = (await session.execute(stmt.execution_options(populate_existing=True))).scalar_one_or_none()
        if p is not None:
            return p
        return await _create_shared(session, user, stmt)


async def _owner_for_shared(session: AsyncSession, user: User) -> int:
    row = (
        (
            await session.execute(
                select(User.id)
                .where(User.role.in_(("superadmin", "admin")), User.is_active.is_(True))
                .order_by(User.id)
            )
        )
        .scalars()
        .first()
    )
    return row or user.id


async def _create_shared(session: AsyncSession, user: User, stmt) -> Project:
    d = await settings_svc.get_tool_pool(session)
    slug = SHARED_SLUG
    if (await session.execute(select(Project).where(Project.slug == slug))).scalar_one_or_none():
        slug = f"{slug}-pool"
    p = Project(
        slug=slug,
        name="工具池",
        description="資料前處理與資料分析服務的任務在這裡排隊執行；配額由管理員在 Dashboard 的「工具池」設定。",
        data_type="TABULAR",
        task_type="classification",
        status="active",
        kind="shared",
        owner_id=await _owner_for_shared(session, user),
        gpu_limit=d.gpu_limit,
        cpu_limit=d.cpu_limit,
        memory_limit_mb=d.memory_limit_mb,
        storage_quota_mb=d.storage_quota_mb,
        max_concurrent_jobs=d.max_concurrent_jobs,
        approved_at=utcnow(),
    )
    session.add(p)
    try:
        await session.flush()
        get_storage().ensure(get_storage().project_dir(p.slug))
        await audit.record(session, user.id, "project.shared.create", "project", p.id, {"slug": p.slug})
        await session.commit()
    except IntegrityError:
        # another process created it meanwhile (unique slug). The rollback expired every loaded row, including
        # ``user`` (lazy loads are not possible in async code), so refresh it before touching it again.
        await session.rollback()
        await session.refresh(user)
    return (
        await session.execute(select(Project).where(Project.kind == "shared").execution_options(populate_existing=True))
    ).scalar_one()


async def sync_shared_quota(session: AsyncSession, pool) -> None:
    """Admin changed the ToolPool setting: the shared project's quota columns follow (the scheduler reads them)."""
    p = (await session.execute(select(Project).where(Project.kind == "shared"))).scalar_one_or_none()
    if p is None:
        return
    p.gpu_limit = pool.gpu_limit
    p.cpu_limit = pool.cpu_limit
    p.memory_limit_mb = pool.memory_limit_mb
    p.storage_quota_mb = pool.storage_quota_mb
    p.max_concurrent_jobs = pool.max_concurrent_jobs
    await session.flush()


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
    session: AsyncSession, user: User, *, statuses: list[str] | None = None, query: str | None = None
) -> list[Project]:
    """Projects the user is a member of (admins: all), standard kind only (the tool pool and legacy personal
    workspaces never show up here). ``statuses`` None → everything except archived."""
    stmt = select(Project).where(Project.kind == "standard")
    if not user.is_admin:
        stmt = stmt.join(ProjectMember, ProjectMember.project_id == Project.id).where(ProjectMember.user_id == user.id)
    stmt = stmt.where(Project.status.in_(statuses)) if statuses else stmt.where(Project.status != "archived")
    if query:
        like = f"%{query.strip()}%"
        stmt = stmt.where((Project.name.ilike(like)) | (Project.slug.ilike(like)))
    rows = (await session.execute(stmt.order_by(Project.created_at.desc()))).scalars().unique().all()
    return list(rows)


async def project_ids_for_user(session: AsyncSession, user: User) -> list[int] | None:
    """None = every project (admin); otherwise the ids of the projects the user is a member of (any status)."""
    if user.is_admin:
        return None
    rows = await session.execute(select(ProjectMember.project_id).where(ProjectMember.user_id == user.id))
    return list(rows.scalars().all())


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
    if project.kind == "shared":
        raise conflict("TOOL_POOL", "工具池不能封存（前處理 / 分析工具需要它）")
    if project.status not in ("active", "completed"):
        raise conflict("PROJECT_NOT_ACTIVE", f"狀態 {project.status} 不能封存")
    project.status = "archived"
    project.archived_at = utcnow()
    await audit.record(session, actor.id, "project.archive", "project", project.id)
    await session.commit()
    return project


async def unarchive(session: AsyncSession, actor: User, project: Project) -> Project:
    if project.status != "archived":
        raise conflict("PROJECT_NOT_ARCHIVED", "專案沒有被封存")
    project.status = "active"
    project.archived_at = None
    await audit.record(session, actor.id, "project.unarchive", "project", project.id)
    await session.commit()
    return project


async def complete(session: AsyncSession, actor: User, project: Project) -> Project:
    """已結束: no new jobs; artifacts, logs and storage stay; the owner or an admin can reopen it."""
    if project.status != "active":
        raise conflict("PROJECT_NOT_ACTIVE", f"狀態 {project.status} 不能結束")
    active = (
        await session.execute(
            select(func.count())
            .select_from(Job)
            .where(Job.project_id == project.id, Job.status.in_(("queued", "scheduled", "running")))
        )
    ).scalar_one()
    if active:
        raise conflict("PROJECT_HAS_ACTIVE_JOBS", f"還有 {active} 個任務未結束，請先取消")
    project.status = "completed"
    project.completed_at = utcnow()
    await audit.record(session, actor.id, "project.complete", "project", project.id)
    await session.commit()
    return project


async def reopen(session: AsyncSession, actor: User, project: Project) -> Project:
    if project.status != "completed":
        raise conflict("PROJECT_NOT_COMPLETED", "專案沒有結束")
    project.status = "active"
    project.completed_at = None
    await audit.record(session, actor.id, "project.reopen", "project", project.id)
    await session.commit()
    return project


async def delete(session: AsyncSession, actor: User, project: Project) -> None:
    """superadmin: remove the project, its jobs, artifacts, data-source references, members and the folder on disk.
    Refused while any job is still queued / scheduled / running. Discussion threads keep their rows but lose the
    link; the application row goes with the project."""
    if project.kind == "shared":
        raise conflict("TOOL_POOL", "工具池不能刪除")
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
    upload_ids = list((await session.execute(select(Upload.id).where(Upload.project_id == project.id))).scalars())
    await session.execute(sql_delete(Upload).where(Upload.project_id == project.id))
    await session.execute(sql_delete(Job).where(Job.project_id == project.id))
    await session.execute(sql_delete(DataSource).where(DataSource.project_id == project.id))
    await session.execute(sql_update(Issue).where(Issue.project_id == project.id).values(project_id=None))
    request_id = project.request_id
    project.request_id = None
    await session.execute(
        sql_update(ProjectRequest).where(ProjectRequest.project_id == project.id).values(project_id=None)
    )
    await session.flush()
    if request_id is not None:
        await session.execute(
            sql_delete(Comment).where(Comment.target_type == "project_request", Comment.target_id == request_id)
        )
        await session.execute(sql_delete(ProjectRequest).where(ProjectRequest.id == request_id))
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
    for upload_id in upload_ids:  # one-time uploads live at uploads/<upload id>, not per project
        storage.remove_tree(f"uploads/{upload_id}")
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
    if body.user_id is not None:
        user = await users_svc.get_by_id(session, body.user_id)
    else:
        user = await users_svc.find_by_username_or_email(session, (body.username_or_email or "").strip())
    if user is None:
        raise not_found("USER_NOT_FOUND", "找不到使用者（對方必須先登入過一次）")
    if project.role_of(user.id):
        raise conflict("ALREADY_MEMBER", "已是成員")
    # Through the relationship, not session.add(): the session keeps `project` (expire_on_commit=False) and its
    # selectin-loaded `members` list must already contain the new row when the response is serialised.
    project.members.append(ProjectMember(user=user, role=body.role, added_by_id=actor.id))
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
    project.members.remove(m)  # delete-orphan cascade deletes the row; the response list is current
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
