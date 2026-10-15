"""Trainer → backend. Authenticated with the per-job token only."""

from __future__ import annotations

from fastapi import APIRouter

from app.core.deps import DbSession, InternalJob
from app.schemas.artifact import ArtifactRead
from app.schemas.common import Ok
from app.schemas.internal import ArtifactRegister, JobSpec, MetricsBody, ResultBody, StatusBody
from app.services import artifacts as artifacts_svc
from app.services import internal as internal_svc

router = APIRouter(prefix="/internal/jobs", tags=["internal"])


@router.get("/{job_id}/spec", response_model=JobSpec)
async def spec(job: InternalJob, session: DbSession) -> JobSpec:
    return await internal_svc.job_spec(session, job)


@router.post("/{job_id}/status", response_model=Ok)
async def status(body: StatusBody, job: InternalJob, session: DbSession) -> Ok:
    await internal_svc.update_status(session, job, body)
    return Ok()


@router.post("/{job_id}/metrics", response_model=Ok)
async def metrics(body: MetricsBody, job: InternalJob, session: DbSession) -> Ok:
    await internal_svc.add_metrics(session, job, body)
    return Ok()


@router.post("/{job_id}/artifacts", response_model=ArtifactRead, status_code=201)
async def register_artifact(body: ArtifactRegister, job: InternalJob, session: DbSession) -> ArtifactRead:
    return ArtifactRead.model_validate(await artifacts_svc.register_from_job(session, job, body))


@router.post("/{job_id}/result", response_model=Ok)
async def result(body: ResultBody, job: InternalJob, session: DbSession) -> Ok:
    await internal_svc.set_result(session, job, body)
    return Ok()
