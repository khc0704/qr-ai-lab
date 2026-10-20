from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request
from fastapi.responses import FileResponse
from sse_starlette.sse import EventSourceResponse

from app.core.deps import ROLE_ORDER, CurrentUser, DbSession, ProjectAccess, project_access
from app.core.errors import forbidden, not_found
from app.events.bus import get_bus
from app.models import Job
from app.routers import _serialize as ser
from app.schemas.artifact import ArtifactRead
from app.schemas.common import Ok
from app.schemas.job import JobRead, LogLinesRead
from app.services import artifacts as artifacts_svc
from app.services import jobs as jobs_svc
from app.services import projects as projects_svc
from app.storage.local import get_storage

router = APIRouter(prefix="/jobs", tags=["jobs"])


def _job_access(min_role: str = "viewer"):
    """Dependency factory (a default argument would become a ``?min_role=`` query parameter)."""

    async def dep(job_id: int, session: DbSession, user: CurrentUser) -> tuple[Job, ProjectAccess]:
        job = await jobs_svc.get(session, job_id)
        if job.project.kind == "shared":
            # tool pool: no members; the creator acts as a member of their own job, admins as owners
            if user.is_admin:
                return job, ProjectAccess(project=job.project, role="owner", user=user)
            if job.created_by_id != user.id:
                raise not_found("JOB_NOT_FOUND", "找不到 job")
            if ROLE_ORDER[min_role] > ROLE_ORDER["member"]:
                raise forbidden("PROJECT_ROLE", f"需要 {min_role} 以上的專案角色")
            return job, ProjectAccess(project=job.project, role="member", user=user)
        access = await project_access(min_role)(session, user, job.project.slug)
        return job, access

    dep.__name__ = f"job_access_{min_role}"
    return dep


JobView = Annotated[tuple[Job, ProjectAccess], Depends(_job_access("viewer"))]


@router.get("", response_model=list[JobRead], summary="我有權限的專案的最近任務（首頁 / 專案列表用）")
async def recent_jobs(
    session: DbSession,
    user: CurrentUser,
    status: str | None = Query(None, description="逗號分隔"),
    kind: str | None = None,
    limit: int = Query(20, ge=1, le=100),
) -> list[JobRead]:
    project_ids = await projects_svc.project_ids_for_user(session, user)
    statuses = [x.strip() for x in status.split(",") if x.strip()] if status else None
    rows = await jobs_svc.list_recent(session, project_ids=project_ids, statuses=statuses, kind=kind, limit=limit)
    return await ser.jobs(session, rows)


@router.get("/{job_id}", response_model=JobRead)
async def get_job(jv: JobView, session: DbSession) -> JobRead:
    return await ser.job(session, jv[0])


@router.post("/{job_id}/cancel", response_model=JobRead, summary="成員取消（queued 立即取消；執行中由 scheduler 停止）")
async def cancel_job(job_id: int, session: DbSession, user: CurrentUser) -> JobRead:
    job, access = await _job_access("member")(job_id, session, user)
    if access.role == "member" and job.created_by_id != user.id:
        raise forbidden("JOB_NOT_OWNER", "成員只能取消自己的任務")
    return await ser.job(session, await jobs_svc.cancel(session, user, job))


@router.delete("/{job_id}", response_model=Ok, summary="刪除已結束的任務（成員刪自己的；maintainer 以上刪任何）")
async def delete_job(job_id: int, session: DbSession, user: CurrentUser) -> Ok:
    """任務紀錄、log、輸出資料夾與它產生的產物一併刪除；還有推論任務在用的模型要先刪除那些任務（409
    ``ARTIFACT_IN_USE``），執行中的任務要先取消（409 ``JOB_ACTIVE``）。工具池任務只有建立者與管理員能刪。"""
    job, access = await _job_access("member")(job_id, session, user)
    if access.role == "member" and job.created_by_id != user.id:
        raise forbidden("JOB_NOT_OWNER", "成員只能刪除自己的任務")
    await jobs_svc.delete(session, user, job)
    return Ok()


@router.get("/{job_id}/artifacts", response_model=list[ArtifactRead])
async def job_artifacts(jv: JobView, session: DbSession) -> list[ArtifactRead]:
    return [ArtifactRead.model_validate(a) for a in await artifacts_svc.list_for_job(session, jv[0].id)]


@router.get("/{job_id}/logs", response_model=LogLinesRead, summary="log 檔分頁（offset 省略 = 最後 limit 行）")
async def job_logs(
    jv: JobView, offset: int | None = Query(None, ge=0), limit: int = Query(500, ge=1, le=5000)
) -> LogLinesRead:
    lines, start, total = await asyncio.to_thread(jobs_svc.read_log, jv[0], offset, limit)
    last_id = await get_bus().last_id(jv[0].id) if offset is None else None
    return LogLinesRead(lines=lines, offset=start, total=total, last_event_id=last_id)


@router.get("/{job_id}/logs/download")
async def download_logs(jv: JobView) -> FileResponse:
    path = jobs_svc.log_file(jv[0])
    if not path.exists():
        raise not_found("LOG_NOT_FOUND", "尚無 log")
    return FileResponse(path, media_type="text/plain", filename=f"job-{jv[0].id}.log")


@router.get("/{job_id}/download", summary="推論輸出 / 前處理結果下載（前處理結果下載後即刪除）")
async def download_output(jv: JobView, background: BackgroundTasks) -> FileResponse:
    job = jv[0]
    rel = (job.result or {}).get("output_path")
    if not rel:
        raise not_found("OUTPUT_NOT_FOUND", "此任務沒有可下載的輸出")
    path = get_storage().abs(rel)
    if not path.is_file():
        gone = (job.result or {}).get("downloaded_at") or (job.result or {}).get("expired_at")
        raise not_found("OUTPUT_NOT_FOUND", "輸出檔已下載並刪除" if gone else "輸出檔不存在")
    if job.kind == "preprocess" and (job.input or {}).get("tool"):
        background.add_task(jobs_svc.mark_output_downloaded, job.id)
    filename = path.name
    if job.kind == "preprocess":
        stem = Path(str((job.input or {}).get("original_filename") or "data")).stem or "data"
        filename = f"{stem}-preprocessed.zip"
    return FileResponse(path, filename=filename)


@router.get("/{job_id}/events", summary="SSE：status / progress / metric / log / end")
async def job_events(jv: JobView, request: Request):
    job = jv[0]
    last_id = request.headers.get("last-event-id")
    bus = get_bus()

    async def gen():
        if not job.is_active:
            for ev in await bus.replay(job.id):
                yield {"id": ev["id"], "event": ev["type"], "data": json.dumps(ev["data"], ensure_ascii=False)}
            yield {"event": "end", "data": json.dumps({"status": job.status})}
            return
        async for ev in bus.subscribe(job.id, last_id):
            if await request.is_disconnected():
                return
            yield {"id": ev["id"], "event": ev["type"], "data": json.dumps(ev["data"], ensure_ascii=False)}

    return EventSourceResponse(gen())
