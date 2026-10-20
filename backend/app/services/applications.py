"""Project applications: a project is created the moment someone applies (status `pending`) and the application
itself (purpose, requested resources, proposed members) lives in `project_requests`, linked through
`projects.request_id`. Review happens on the project: pending → in_review → active (quota set) or rejected
(editable, resubmit → pending). Withdrawing a pending application deletes the project again."""

from __future__ import annotations

import re

from sqlalchemy import delete as sql_delete
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.catalog import loader
from app.core.errors import bad_request, conflict, forbidden
from app.db.base import utcnow
from app.models import Comment, Project, ProjectMember, ProjectRequest, User
from app.schemas.project import PENDING_STATUSES, ApplicationUpdate, ApproveBody, ProjectApplyBody, RejectBody
from app.services import audit, comments
from app.storage.local import get_storage

TARGET = "project_request"  # comment target type (the review thread hangs off the application row)


def _name(u: User) -> str:
    return u.display_name or u.username


def slugify(title: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    base = re.sub(r"-{2,}", "-", base)[:40].strip("-")
    return base if len(base) >= 2 else "project"


async def _unique_slug(session: AsyncSession, base: str) -> str:
    taken = set((await session.execute(select(Project.slug).where(Project.slug.like(f"{base}%")))).scalars().all())
    if base not in taken:
        return base
    n = 2
    while f"{base}-{n}" in taken:
        n += 1
    return f"{base}-{n}"


def _assert_applicant(user: User, project: Project) -> None:
    if project.owner_id != user.id and not user.is_admin:
        raise forbidden("REQUEST_NOT_OWNER", "只有申請人可以操作")


def _application(project: Project) -> ProjectRequest:
    r = project.application
    if r is None:
        raise conflict("NO_APPLICATION", "這個專案不是經由申請建立的")
    return r


def supported_tasks(data_type: str) -> list[str]:
    """Tasks at least one model family can run on this data type (the catalog is the source of truth)."""
    return [t for t in loader.load_catalog()["tasks"] if loader.families_for(data_type, t)]


def check_task(data_type: str, task_type: str) -> None:
    tasks = supported_tasks(data_type)
    if task_type not in tasks:
        raise bad_request(
            "TASK_NOT_SUPPORTED",
            f"{data_type} 沒有模型支援 {task_type}；可選：{', '.join(tasks)}",
        )


async def apply(session: AsyncSession, user: User, body: ProjectApplyBody, *, pool_gpu: int) -> Project:
    if body.requested_gpu > pool_gpu:
        raise bad_request("GPU_EXCEEDS_POOL", f"GPU 需求 {body.requested_gpu} 超過資源池 {pool_gpu}")
    check_task(body.data_type, body.task_type)
    slug = await _unique_slug(session, body.proposed_slug or slugify(body.title))
    r = ProjectRequest(
        applicant_id=user.id,
        **body.model_dump(exclude={"members", "proposed_slug"}),
        proposed_slug=slug,
        members=[m.model_dump() for m in body.members],
        status="submitted",
    )
    session.add(r)
    await session.flush()
    project = Project(
        slug=slug,
        name=body.title[:120],
        description=body.purpose,
        data_type=body.data_type,
        task_type=body.task_type,
        status="pending",
        kind="standard",
        owner_id=user.id,
        request_id=r.id,
        gpu_limit=0,
        cpu_limit=body.requested_cpu,
        memory_limit_mb=body.requested_memory_mb,
        storage_quota_mb=body.requested_storage_mb,
    )
    session.add(project)
    await session.flush()
    r.project_id = project.id
    session.add(ProjectMember(project_id=project.id, user_id=user.id, role="owner", added_by_id=user.id))
    await comments.add(session, TARGET, r.id, None, f"{_name(user)} 送出申請", kind="system")
    await audit.record(session, user.id, "project.apply", "project", project.id, {"slug": slug})
    await session.commit()
    return await _reload(session, project.id)


async def _reload(session: AsyncSession, project_id: int) -> Project:
    return (
        await session.execute(select(Project).where(Project.id == project_id).execution_options(populate_existing=True))
    ).scalar_one()


async def update_application(session: AsyncSession, user: User, project: Project, body: ApplicationUpdate) -> Project:
    _assert_applicant(user, project)
    r = _application(project)
    if project.status not in ("pending", "rejected"):
        raise conflict("REQUEST_NOT_EDITABLE", f"狀態 {project.status} 不能修改申請")
    data = body.model_dump(exclude_none=True)
    if body.data_type is not None or body.task_type is not None:
        check_task(body.data_type or project.data_type, body.task_type or project.task_type)
    if "members" in data:
        data["members"] = [m.model_dump() for m in body.members or []]
    for k, v in data.items():
        setattr(r, k, v)
    if body.title is not None:
        project.name = body.title[:120]
    if body.purpose is not None:
        project.description = body.purpose
    if body.data_type is not None:
        project.data_type = body.data_type
    if body.task_type is not None:
        project.task_type = body.task_type
    if body.requested_cpu is not None:
        project.cpu_limit = body.requested_cpu
    if body.requested_memory_mb is not None:
        project.memory_limit_mb = body.requested_memory_mb
    if body.requested_storage_mb is not None:
        project.storage_quota_mb = body.requested_storage_mb
    if project.status == "rejected":
        project.status = "pending"
        r.status = "submitted"
        r.submitted_at = utcnow()
        r.review_note = None
        r.reviewed_at = None
        await comments.add(session, TARGET, r.id, None, f"{_name(user)} 修改後重新送出申請", kind="system")
    await session.commit()
    return await _reload(session, project.id)


async def withdraw(session: AsyncSession, user: User, project: Project) -> None:
    """A pending application is withdrawn by deleting the project again (nothing can have run yet)."""
    _assert_applicant(user, project)
    r = _application(project)
    if project.status not in (*PENDING_STATUSES, "rejected"):
        raise conflict("REQUEST_NOT_WITHDRAWABLE", f"狀態 {project.status} 不能撤回")
    await audit.record(
        session, user.id, "project.withdraw", "project", project.id, {"slug": project.slug, "title": r.title}
    )
    r.project_id = None
    project.request_id = None
    await session.flush()
    await session.execute(sql_delete(Comment).where(Comment.target_type == TARGET, Comment.target_id == r.id))
    await session.delete(project)  # members cascade
    await session.delete(r)
    await session.commit()


async def review(session: AsyncSession, admin: User, project: Project) -> Project:
    r = _application(project)
    if project.status != "pending":
        raise conflict("REQUEST_NOT_SUBMITTED", f"狀態 {project.status} 不能開始審核")
    project.status = "in_review"
    r.status = "in_review"
    r.reviewer_id = admin.id
    await comments.add(session, TARGET, r.id, None, f"管理員 {_name(admin)} 開始審核", kind="system")
    await session.commit()
    return await _reload(session, project.id)


async def reject(session: AsyncSession, admin: User, project: Project, body: RejectBody) -> Project:
    r = _application(project)
    if project.status not in PENDING_STATUSES:
        raise conflict("REQUEST_NOT_REVIEWABLE", f"狀態 {project.status} 不能退回")
    project.status = "rejected"
    r.status = "rejected"
    r.reviewer_id = admin.id
    r.review_note = body.review_note
    r.reviewed_at = utcnow()
    await comments.add(
        session, TARGET, r.id, None, f"管理員 {_name(admin)} 退回了申請：{body.review_note}", kind="system"
    )
    await audit.record(session, admin.id, "project.reject", "project", project.id, {"review_note": body.review_note})
    await session.commit()
    return await _reload(session, project.id)


def validate_quota_against_pool(body: ApproveBody, pool_gpu: int) -> None:
    if body.gpu_limit > pool_gpu:
        raise bad_request("QUOTA_EXCEEDS_POOL", f"GPU 配額 {body.gpu_limit} 超過資源池 {pool_gpu}")


async def approve(session: AsyncSession, admin: User, project: Project, body: ApproveBody) -> Project:
    """One transaction: quota + members + data dir + states + audit."""
    r = _application(project)
    if project.status not in PENDING_STATUSES:
        raise conflict("REQUEST_NOT_REVIEWABLE", f"狀態 {project.status} 不能核准")
    if body.name:
        project.name = body.name[:120]
    project.gpu_limit = body.gpu_limit
    project.cpu_limit = body.cpu_limit
    project.memory_limit_mb = body.memory_limit_mb
    project.storage_quota_mb = body.storage_quota_mb
    project.max_concurrent_jobs = body.max_concurrent_jobs
    project.status = "active"
    project.approved_by_id = admin.id
    project.approved_at = utcnow()
    wanted = body.members if body.members is not None else [type("M", (), m)() for m in (r.members or [])]
    skipped: list[str] = []
    present = {m.user_id for m in project.members}
    for m in wanted:
        email = getattr(m, "email", None)
        role = getattr(m, "role", "member")
        u = (await session.execute(select(User).where(User.email == email))).scalar_one_or_none()
        if u is None:
            skipped.append(str(email))
            continue
        if u.id in present:
            continue
        session.add(ProjectMember(project_id=project.id, user_id=u.id, role=role, added_by_id=admin.id))
        present.add(u.id)
    get_storage().ensure(get_storage().project_dir(project.slug))
    r.status = "approved"
    r.reviewer_id = admin.id
    r.review_note = body.review_note
    r.reviewed_at = utcnow()
    note = f"管理員 {_name(admin)} 核准了申請，專案 {project.slug} 開始進行"
    if skipped:
        note += f"（尚未登入過、未加入：{', '.join(skipped)}）"
    await comments.add(session, TARGET, r.id, None, note, kind="system")
    await audit.record(
        session,
        admin.id,
        "project.approve",
        "project",
        project.id,
        {"slug": project.slug, "quota": body.model_dump(exclude={"members"})},
    )
    await session.commit()
    return await _reload(session, project.id)
