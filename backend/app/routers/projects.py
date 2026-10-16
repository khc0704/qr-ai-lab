from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile

from app.core.deps import CurrentUser, DbSession, ProjectAccess, project_access, require_perm
from app.models import User
from app.routers import _serialize as ser
from app.schemas.artifact import ArtifactRead
from app.schemas.common import Ok, Page
from app.schemas.data_source import DataSourceCreate, DataSourceRead, DataSourceUpdate
from app.schemas.job import JobCreate, JobRead
from app.schemas.project import MemberAdd, MemberUpdate, ProjectRead, ProjectUpdate, QuotaUpdate
from app.schemas.upload import PreprocessPreviewBody, UploadRead
from app.services import (
    artifacts as artifacts_svc,
)
from app.services import (
    data_sources as ds_svc,
)
from app.services import (
    jobs as jobs_svc,
)
from app.services import (
    projects as projects_svc,
)
from app.services import (
    uploads as uploads_svc,
)

router = APIRouter(prefix="/projects", tags=["projects"])

Viewer = Annotated[ProjectAccess, Depends(project_access("viewer"))]
Member = Annotated[ProjectAccess, Depends(project_access("member"))]
Maintainer = Annotated[ProjectAccess, Depends(project_access("maintainer"))]
Owner = Annotated[ProjectAccess, Depends(project_access("owner"))]
QuotaManager = Annotated[User, Depends(require_perm("quota.manage"))]
ProjectDeleter = Annotated[User, Depends(require_perm("projects.delete"))]


@router.get("", response_model=list[ProjectRead], summary="我有權限的專案")
async def list_projects(
    session: DbSession, user: CurrentUser, include_archived: bool = False, include_personal: bool = False
) -> list[ProjectRead]:
    """include_personal=true 也列出個人工作區（工具任務的專案；管理員調配額時需要）。"""
    return await ser.projects(
        session, await projects_svc.list_for_user(session, user, include_archived, include_personal)
    )


@router.get("/{slug}", response_model=ProjectRead)
async def get_project(access: Viewer, session: DbSession) -> ProjectRead:
    return await ser.project(session, access.project)


@router.patch("/{slug}", response_model=ProjectRead)
async def update_project(body: ProjectUpdate, access: Owner, session: DbSession) -> ProjectRead:
    return await ser.project(session, await projects_svc.update(session, access.user, access.project, body))


@router.post("/{slug}/archive", response_model=ProjectRead)
async def archive_project(access: Owner, session: DbSession) -> ProjectRead:
    return await ser.project(session, await projects_svc.archive(session, access.user, access.project))


@router.post("/{slug}/unarchive", response_model=ProjectRead, summary="解除封存（owner）")
async def unarchive_project(access: Owner, session: DbSession) -> ProjectRead:
    return await ser.project(session, await projects_svc.unarchive(session, access.user, access.project))


@router.delete("/{slug}", response_model=Ok, summary="刪除專案與所有產物（superadmin）")
async def delete_project(slug: str, session: DbSession, admin: ProjectDeleter) -> Ok:
    """不可復原：刪除任務、產物、資料來源設定、成員與專案資料夾。還有未結束的任務時拒絕。"""
    project = await projects_svc.get_by_slug(session, slug)
    await projects_svc.delete(session, admin, project)
    return Ok()


@router.patch("/{slug}/quota", response_model=ProjectRead, summary="調整配額（superadmin）")
async def update_quota(slug: str, body: QuotaUpdate, session: DbSession, admin: QuotaManager) -> ProjectRead:
    project = await projects_svc.get_by_slug(session, slug)
    return await ser.project(session, await projects_svc.update_quota(session, admin, project, body))


# --- members ---


@router.post("/{slug}/members", response_model=ProjectRead, status_code=201)
async def add_member(body: MemberAdd, access: Maintainer, session: DbSession) -> ProjectRead:
    return await ser.project(session, await projects_svc.add_member(session, access.user, access.project, body))


@router.patch("/{slug}/members/{user_id}", response_model=ProjectRead)
async def update_member(user_id: int, body: MemberUpdate, access: Maintainer, session: DbSession) -> ProjectRead:
    return await ser.project(
        session, await projects_svc.update_member(session, access.user, access.project, user_id, body)
    )


@router.delete("/{slug}/members/{user_id}", response_model=ProjectRead)
async def remove_member(user_id: int, access: Maintainer, session: DbSession) -> ProjectRead:
    return await ser.project(session, await projects_svc.remove_member(session, access.user, access.project, user_id))


# --- data sources ---


@router.get("/{slug}/data-sources", response_model=list[DataSourceRead])
async def list_data_sources(access: Viewer, session: DbSession) -> list[DataSourceRead]:
    return [ser.data_source(d) for d in await ds_svc.list_for_project(session, access.project.id)]


@router.post("/{slug}/data-sources", response_model=DataSourceRead, status_code=201)
async def create_data_source(body: DataSourceCreate, access: Member, session: DbSession) -> DataSourceRead:
    return ser.data_source(await ds_svc.create(session, access.user, access.project, body))


@router.patch("/{slug}/data-sources/{ds_id}", response_model=DataSourceRead)
async def update_data_source(ds_id: int, body: DataSourceUpdate, access: Member, session: DbSession) -> DataSourceRead:
    ds = await ds_svc.get(session, access.project, ds_id)
    return ser.data_source(await ds_svc.update(session, access.user, access.project, ds, body))


@router.delete("/{slug}/data-sources/{ds_id}", response_model=Ok)
async def delete_data_source(ds_id: int, access: Member, session: DbSession) -> Ok:
    await ds_svc.delete(session, access.user, access.project, await ds_svc.get(session, access.project, ds_id))
    return Ok()


@router.post("/{slug}/data-sources/{ds_id}/check", response_model=DataSourceRead, summary="輕量連線檢查，不下載內容")
async def check_data_source(ds_id: int, access: Member, session: DbSession) -> DataSourceRead:
    return ser.data_source(await ds_svc.check(session, await ds_svc.get(session, access.project, ds_id)))


# --- uploads (one-time) ---


@router.post(
    "/{slug}/uploads", response_model=UploadRead, status_code=201, summary="一次性上傳；建立任務時綁定，任務結束即刪"
)
async def upload(
    access: Member, session: DbSession, file: UploadFile = File(...), format: str | None = Form(None)
) -> UploadRead:
    return UploadRead.model_validate(
        await uploads_svc.create_from_upload(session, access.user, access.project, file, format)
    )


@router.post(
    "/{slug}/uploads/{upload_id}/preview",
    summary="對上傳檔抽樣套用前處理步驟，回傳前後對照（不儲存）",
)
async def preview_upload(upload_id: int, body: PreprocessPreviewBody, access: Member, session: DbSession) -> dict:
    return await uploads_svc.preview(
        session, access.project, upload_id, body.steps, sample=body.sample, spec=body.spec, task_type=body.task_type
    )


# --- jobs ---


@router.get("/{slug}/jobs", response_model=Page[JobRead])
async def list_jobs(
    access: Viewer,
    session: DbSession,
    status: str | None = None,
    kind: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> Page[JobRead]:
    statuses = [s for s in status.split(",") if s] if status else None
    rows, total = await jobs_svc.list_jobs(
        session, project_id=access.project.id, statuses=statuses, kind=kind, page=page, page_size=page_size
    )
    return Page(items=await ser.jobs(session, rows), total=total, page=page, page_size=page_size)


@router.post("/{slug}/jobs", response_model=JobRead, status_code=202, summary="建立訓練或推論任務（進入全域佇列）")
async def create_job(body: JobCreate, access: Member, session: DbSession) -> JobRead:
    return await ser.job(session, await jobs_svc.create(session, access.user, access.project, body))


# --- artifacts ---


@router.get("/{slug}/artifacts", response_model=list[ArtifactRead])
async def list_artifacts(access: Viewer, session: DbSession, kind: str | None = None) -> list[ArtifactRead]:
    return [
        ArtifactRead.model_validate(a) for a in await artifacts_svc.list_for_project(session, access.project.id, kind)
    ]
