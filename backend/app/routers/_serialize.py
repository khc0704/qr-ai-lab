"""Helpers that turn ORM rows into read schemas with derived fields (slugs, usage, queue position)."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DataSource, Issue, Job, Project
from app.schemas.data_source import DataSourceRead
from app.schemas.issue import IssueRead
from app.schemas.job import JobRead
from app.schemas.project import ApplicationRead, ProjectRead
from app.services import (
    issues as issues_svc,
)
from app.services import (
    jobs as jobs_svc,
)
from app.services import (
    node as node_svc,
)
from app.services import (
    projects as projects_svc,
)
from app.services import (
    settings as settings_svc,
)


async def projects(session: AsyncSession, rows: list[Project]) -> list[ProjectRead]:
    usage = await projects_svc.usage_map(session, [p.id for p in rows])
    out = []
    for p in rows:
        app = ApplicationRead.model_validate(p.application) if p.application is not None else None
        out.append(ProjectRead.model_validate(p).model_copy(update={"usage": usage[p.id], "application": app}))
    return out


async def project(session: AsyncSession, p: Project) -> ProjectRead:
    return (await projects(session, [p]))[0]


async def issues(session: AsyncSession, rows: list[Issue]) -> list[IssueRead]:
    slugs = await issues_svc.slug_map(session, rows)
    return [
        IssueRead.model_validate(i).model_copy(update={"project_slug": slugs.get(i.project_id or -1)}) for i in rows
    ]


def data_source(ds: DataSource) -> DataSourceRead:
    return DataSourceRead.model_validate(ds).model_copy(update={"has_credentials": ds.credentials_enc is not None})


async def jobs(session: AsyncSession, rows: list[Job], *, with_queue: bool = True) -> list[JobRead]:
    positions: dict[int, int] = {}
    reasons: dict[int, str | None] = {}
    if with_queue and any(j.status == "queued" for j in rows):
        positions = await jobs_svc.queue_positions(session)
        pool = await settings_svc.get_resource_pool(session)
        alloc = await node_svc.allocated(session)
        per_project = {
            pid: u.model_dump()
            for pid, u in (await projects_svc.usage_map(session, list({j.project_id for j in rows}))).items()
        }
        for j in rows:
            if j.status == "queued":
                reasons[j.id] = jobs_svc.wait_reason(j, pool, alloc.model_dump(), per_project)
    out = []
    for j in rows:
        out.append(
            JobRead.model_validate(j).model_copy(
                update={
                    "project_slug": j.project.slug,
                    "project_name": j.project.name,
                    "queue_position": positions.get(j.id),
                    "wait_reason": reasons.get(j.id),
                }
            )
        )
    return out


async def job(session: AsyncSession, j: Job) -> JobRead:
    return (await jobs(session, [j]))[0]
