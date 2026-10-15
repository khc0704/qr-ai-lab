from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request
from fastapi.responses import FileResponse
from sse_starlette.sse import EventSourceResponse

from app.core.deps import CurrentUser, DbSession, ProjectAccess, project_access
from app.core.errors import forbidden, not_found
from app.events.bus import get_bus
from app.models import Job
from app.routers import _serialize as ser
from app.schemas.artifact import ArtifactRead
from app.schemas.job import JobRead, LogLinesRead
from app.services import artifacts as artifacts_svc
from app.services import jobs as jobs_svc
from app.services import projects as projects_svc
from app.storage.local import get_storage

router = APIRouter(prefix="/jobs", tags=["jobs"])


async def _job_access(
    job_id: int, session: DbSession, user: CurrentUser, min_role: str = "viewer"
) -> tuple[Job, ProjectAccess]:
    job = await jobs_svc.get(session, job_id)
    access = await project_access(min_role)(session, user, job.project.slug)
    return job, access


JobView = Annotated[tuple[Job, ProjectAccess], Depends(_job_access)]


@router.get("", response_model=list[JobRead], summary="我有權限的專案的最近任務（首頁 / 專案列表用）")
async def recent_jobs(
    session: DbSession,
    user: CurrentUser,
    status: str | None = Query(None, description="逗號分隔"),
    kind: str | None = None,
    limit: int = Query(20, ge=1, le=100),
) -> list[JobRead]:
    project_ids = None
    if not user.is_admin:
        project_ids = [p.id for p in await projects_svc.list_for_user(session, user, include_archived=True)]
    statuses = [x.strip() for x in status.split(",") if x.strip()] if status else None
    rows = await jobs_svc.list_recent(session, project_ids=project_ids, statuses=statuses, kind=kind, limit=limit)
    return await ser.jobs(session, rows)


@router.get("/{job_id}", response_model=JobRead)
async def get_job(jv: JobView, session: DbSession) -> JobRead:
    return await ser.job(session, jv[0])


@router.post("/{job_id}/cancel", response_model=JobRead, summary="成員取消（queued 立即取消；執行中由 scheduler 停止）")
async def cancel_job(job_id: int, session: DbSession, user: CurrentUser) -> JobRead:
    job, access = await _job_access(job_id, session, user, "member")
    if access.role == "member" and job.created_by_id != user.id:
        raise forbidden("JOB_NOT_OWNER", "成員只能取消自己的任務")
    return await ser.job(session, await jobs_svc.cancel(session, user, job))


@router.get("/{job_id}/artifacts", response_model=list[ArtifactRead])
async def job_artifacts(jv: JobView, session: DbSession) -> list[ArtifactRead]:
    return [ArtifactRead.model_validate(a) for a in await artifacts_svc.list_for_job(session, jv[0].id)]


@router.get("/{job_id}/logs", response_model=LogLinesRead, summary="log 檔分頁（offset 省略 = 最後 limit 行）")
async def job_logs(
    jv: JobView, offset: int | None = Query(None, ge=0), limit: int = Query(500, ge=1, le=5000)
) -> LogLinesRead:
    lines, start, total = jobs_svc.read_log(jv[0], offset, limit)
    return LogLinesRead(lines=lines, offset=start, total=total)


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
