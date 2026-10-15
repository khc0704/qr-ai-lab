from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.core.deps import CurrentUser, DbSession, require_perm
from app.core.errors import forbidden
from app.models import User
from app.routers import _serialize as ser
from app.schemas.common import Page
from app.schemas.issue import CommentCreate, CommentRead
from app.schemas.project import ProjectRead
from app.schemas.project_request import (
    ApproveBody,
    ProjectRequestCreate,
    ProjectRequestRead,
    ProjectRequestUpdate,
    RejectBody,
)
from app.services import comments as comments_svc
from app.services import project_requests as requests_svc
from app.services import settings as settings_svc

router = APIRouter(prefix="/project-requests", tags=["project-requests"])
Reviewer = Annotated[User, Depends(require_perm("requests.review"))]


async def _one(session, r) -> ProjectRequestRead:
    return (await ser.requests(session, [r]))[0]


def _visible(user, r) -> None:
    if not (user.is_admin or r.applicant_id == user.id):
        raise forbidden("REQUEST_FORBIDDEN", "只有申請人或管理員可以檢視")


@router.get("", response_model=Page[ProjectRequestRead], summary="我的申請；admin 看全部")
async def list_requests(
    session: DbSession,
    user: CurrentUser,
    status: str | None = Query(None, description="逗號分隔，pending = submitted,in_review"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> Page[ProjectRequestRead]:
    statuses = None
    if status:
        statuses = (
            ["submitted", "in_review"] if status == "pending" else [s.strip() for s in status.split(",") if s.strip()]
        )
    rows, total = await requests_svc.list_requests(
        session, applicant_id=None if user.is_admin else user.id, statuses=statuses, page=page, page_size=page_size
    )
    return Page(items=await ser.requests(session, rows), total=total, page=page, page_size=page_size)


@router.post("", response_model=ProjectRequestRead, status_code=201)
async def create_request(body: ProjectRequestCreate, session: DbSession, user: CurrentUser) -> ProjectRequestRead:
    pool = await settings_svc.get_resource_pool(session)
    if body.requested_gpu > len(pool.gpu_indices):
        from app.core.errors import bad_request

        raise bad_request("GPU_EXCEEDS_POOL", f"GPU 需求 {body.requested_gpu} 超過資源池 {len(pool.gpu_indices)}")
    return await _one(session, await requests_svc.create(session, user, body))


@router.get("/{request_id}", response_model=ProjectRequestRead)
async def get_request(request_id: int, session: DbSession, user: CurrentUser) -> ProjectRequestRead:
    r = await requests_svc.get(session, request_id)
    _visible(user, r)
    return await _one(session, r)


@router.patch("/{request_id}", response_model=ProjectRequestRead, summary="申請人修改（submitted / rejected 時）")
async def update_request(
    request_id: int, body: ProjectRequestUpdate, session: DbSession, user: CurrentUser
) -> ProjectRequestRead:
    r = await requests_svc.get(session, request_id)
    return await _one(session, await requests_svc.update(session, user, r, body))


@router.get("/{request_id}/comments", response_model=list[CommentRead])
async def list_comments(request_id: int, session: DbSession, user: CurrentUser) -> list[CommentRead]:
    r = await requests_svc.get(session, request_id)
    _visible(user, r)
    return [CommentRead.model_validate(c) for c in await comments_svc.list_for(session, "project_request", request_id)]


@router.post("/{request_id}/comments", response_model=CommentRead, status_code=201)
async def add_comment(request_id: int, body: CommentCreate, session: DbSession, user: CurrentUser) -> CommentRead:
    r = await requests_svc.get(session, request_id)
    _visible(user, r)
    c = await comments_svc.add(session, "project_request", request_id, user.id, body.body)
    await session.commit()
    return CommentRead.model_validate(c)


@router.post("/{request_id}/withdraw", response_model=ProjectRequestRead)
async def withdraw(request_id: int, session: DbSession, user: CurrentUser) -> ProjectRequestRead:
    return await _one(session, await requests_svc.withdraw(session, user, await requests_svc.get(session, request_id)))


@router.post("/{request_id}/review", response_model=ProjectRequestRead, summary="開始審核（admin）")
async def review(request_id: int, session: DbSession, admin: Reviewer) -> ProjectRequestRead:
    return await _one(session, await requests_svc.review(session, admin, await requests_svc.get(session, request_id)))


@router.post("/{request_id}/approve", response_model=ProjectRead, status_code=201, summary="核准並建立專案（admin）")
async def approve(request_id: int, body: ApproveBody, session: DbSession, admin: Reviewer) -> ProjectRead:
    pool = await settings_svc.get_resource_pool(session)
    requests_svc.validate_quota_against_pool(body, len(pool.gpu_indices))
    project = await requests_svc.approve(session, admin, await requests_svc.get(session, request_id), body)
    return await ser.project(session, project)


@router.post("/{request_id}/reject", response_model=ProjectRequestRead, summary="退回（admin）")
async def reject(request_id: int, body: RejectBody, session: DbSession, admin: Reviewer) -> ProjectRequestRead:
    return await _one(
        session, await requests_svc.reject(session, admin, await requests_svc.get(session, request_id), body)
    )
