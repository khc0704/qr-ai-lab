from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import bad_request, conflict, forbidden, not_found
from app.db.base import utcnow
from app.models import Project, ProjectMember, ProjectRequest, User
from app.schemas.project_request import ApproveBody, ProjectRequestCreate, ProjectRequestUpdate, RejectBody
from app.services import audit, comments
from app.storage.local import get_storage


def _name(u: User) -> str:
    return u.display_name or u.username


async def get(session: AsyncSession, request_id: int) -> ProjectRequest:
    r = await session.get(ProjectRequest, request_id)
    if r is None:
        raise not_found("REQUEST_NOT_FOUND", "找不到申請")
    return r


async def slug_map(session: AsyncSession, requests: list[ProjectRequest]) -> dict[int, str]:
    ids = {r.project_id for r in requests if r.project_id}
    if not ids:
        return {}
    rows = (await session.execute(select(Project.id, Project.slug).where(Project.id.in_(ids)))).all()
    return {pid: slug for pid, slug in rows}


async def list_requests(
    session: AsyncSession, *, applicant_id: int | None, statuses: list[str] | None, page: int, page_size: int
) -> tuple[list[ProjectRequest], int]:
    stmt = select(ProjectRequest)
    if applicant_id:
        stmt = stmt.where(ProjectRequest.applicant_id == applicant_id)
    if statuses:
        stmt = stmt.where(ProjectRequest.status.in_(statuses))
    total = (await session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (
        (
            await session.execute(
                stmt.order_by(ProjectRequest.submitted_at.desc(), ProjectRequest.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        .scalars()
        .all()
    )
    return list(rows), total


async def create(session: AsyncSession, user: User, body: ProjectRequestCreate) -> ProjectRequest:
    r = ProjectRequest(
        applicant_id=user.id, **body.model_dump(exclude={"members"}), members=[m.model_dump() for m in body.members]
    )
    session.add(r)
    await session.commit()
    return await get(session, r.id)


def _assert_applicant(user: User, r: ProjectRequest) -> None:
    if r.applicant_id != user.id and not user.is_admin:
        raise forbidden("REQUEST_NOT_OWNER", "只有申請人可以操作")


async def update(session: AsyncSession, user: User, r: ProjectRequest, body: ProjectRequestUpdate) -> ProjectRequest:
    _assert_applicant(user, r)
    if r.status not in ("submitted", "rejected"):
        raise conflict("REQUEST_NOT_EDITABLE", f"狀態 {r.status} 不能修改")
    data = body.model_dump(exclude_none=True)
    if "members" in data:
        data["members"] = [m.model_dump() for m in body.members or []]
    for k, v in data.items():
        setattr(r, k, v)
    if r.status == "rejected":
        r.status = "submitted"
        r.submitted_at = utcnow()
        r.review_note = None
        await comments.add(session, "project_request", r.id, None, f"{_name(user)} 修改後重新送出申請", kind="system")
    await session.commit()
    return await get(session, r.id)


async def withdraw(session: AsyncSession, user: User, r: ProjectRequest) -> ProjectRequest:
    _assert_applicant(user, r)
    if r.status not in ("submitted", "in_review"):
        raise conflict("REQUEST_NOT_WITHDRAWABLE", f"狀態 {r.status} 不能撤回")
    r.status = "withdrawn"
    await comments.add(session, "project_request", r.id, None, f"{_name(user)} 撤回了申請", kind="system")
    await session.commit()
    return await get(session, r.id)


async def review(session: AsyncSession, admin: User, r: ProjectRequest) -> ProjectRequest:
    if r.status != "submitted":
        raise conflict("REQUEST_NOT_SUBMITTED", f"狀態 {r.status} 不能開始審核")
    r.status = "in_review"
    r.reviewer_id = admin.id
    r.reviewer = admin
    await comments.add(session, "project_request", r.id, None, f"管理員 {_name(admin)} 開始審核", kind="system")
    await session.commit()
    return await get(session, r.id)


async def reject(session: AsyncSession, admin: User, r: ProjectRequest, body: RejectBody) -> ProjectRequest:
    if r.status not in ("submitted", "in_review"):
        raise conflict("REQUEST_NOT_REVIEWABLE", f"狀態 {r.status} 不能退回")
    r.status = "rejected"
    r.reviewer_id = admin.id
    r.reviewer = admin
    r.review_note = body.review_note
    r.reviewed_at = utcnow()
    await comments.add(
        session, "project_request", r.id, None, f"管理員 {_name(admin)} 退回了申請：{body.review_note}", kind="system"
    )
    await audit.record(
        session, admin.id, "project_request.reject", "project_request", r.id, {"review_note": body.review_note}
    )
    await session.commit()
    return await get(session, r.id)


async def approve(session: AsyncSession, admin: User, r: ProjectRequest, body: ApproveBody) -> Project:
    """One transaction: project + members + data dir + request state + audit."""
    if r.status not in ("submitted", "in_review"):
        raise conflict("REQUEST_NOT_REVIEWABLE", f"狀態 {r.status} 不能核准")
    if (await session.execute(select(Project).where(Project.slug == body.slug))).scalar_one_or_none():
        raise conflict("SLUG_TAKEN", f"slug {body.slug} 已被使用")
    project = Project(
        slug=body.slug,
        name=(body.name or r.title)[:120],  # projects.name is VARCHAR(120); titles may be 200
        description=r.purpose,
        data_type=r.data_type,
        task_type=r.task_type,
        owner_id=r.applicant_id,
        request_id=r.id,
        gpu_limit=body.gpu_limit,
        cpu_limit=body.cpu_limit,
        memory_limit_mb=body.memory_limit_mb,
        storage_quota_mb=body.storage_quota_mb,
        max_concurrent_jobs=body.max_concurrent_jobs,
        approved_by_id=admin.id,
        approved_at=utcnow(),
    )
    session.add(project)
    await session.flush()
    session.add(ProjectMember(project_id=project.id, user_id=r.applicant_id, role="owner", added_by_id=admin.id))
    wanted = body.members if body.members is not None else [type("M", (), m)() for m in (r.members or [])]
    skipped: list[str] = []
    for m in wanted:
        email = getattr(m, "email", None)
        role = getattr(m, "role", "member")
        u = (await session.execute(select(User).where(User.email == email))).scalar_one_or_none()
        if u is None:
            skipped.append(email)
            continue
        if u.id == r.applicant_id:
            continue
        session.add(ProjectMember(project_id=project.id, user_id=u.id, role=role, added_by_id=admin.id))
    get_storage().ensure(get_storage().project_dir(project.slug))
    r.status = "approved"
    r.reviewer_id = admin.id
    r.reviewer = admin
    r.review_note = body.review_note
    r.reviewed_at = utcnow()
    r.project_id = project.id
    note = f"管理員 {_name(admin)} 核准了申請，專案 {project.slug} 已建立"
    if skipped:
        note += f"（尚未登入過、未加入：{', '.join(skipped)}）"
    await comments.add(session, "project_request", r.id, None, note, kind="system")
    await audit.record(
        session,
        admin.id,
        "project_request.approve",
        "project_request",
        r.id,
        {"project_id": project.id, "slug": project.slug, "quota": body.model_dump(exclude={"members"})},
    )
    await session.commit()
    return (await session.execute(select(Project).where(Project.id == project.id))).scalar_one()


def validate_quota_against_pool(body: ApproveBody, pool_gpu: int) -> None:
    if body.gpu_limit > pool_gpu:
        raise bad_request("QUOTA_EXCEEDS_POOL", f"GPU 配額 {body.gpu_limit} 超過資源池 {pool_gpu}")
