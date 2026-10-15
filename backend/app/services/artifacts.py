from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import bad_request, conflict, not_found
from app.models import Artifact, Job, Project, User
from app.schemas.internal import ArtifactRegister
from app.services import audit
from app.services import projects as projects_svc
from app.storage.local import get_storage


async def list_for_project(session: AsyncSession, project_id: int, kind: str | None = None) -> list[Artifact]:
    stmt = select(Artifact).where(Artifact.project_id == project_id)
    if kind:
        stmt = stmt.where(Artifact.kind == kind)
    return list((await session.execute(stmt.order_by(Artifact.created_at.desc(), Artifact.id.desc()))).scalars().all())


async def list_for_job(session: AsyncSession, job_id: int) -> list[Artifact]:
    return list(
        (await session.execute(select(Artifact).where(Artifact.job_id == job_id).order_by(Artifact.id))).scalars().all()
    )


async def get(session: AsyncSession, artifact_id: int) -> Artifact:
    a = await session.get(Artifact, artifact_id)
    if a is None:
        raise not_found("ARTIFACT_NOT_FOUND", "找不到產物")
    return a


async def set_default(session: AsyncSession, actor: User, artifact: Artifact, value: bool) -> Artifact:
    if artifact.kind != "model":
        raise bad_request("NOT_A_MODEL", "只有模型可以設為預設")
    if value:
        others = (
            (
                await session.execute(
                    select(Artifact).where(
                        Artifact.project_id == artifact.project_id,
                        Artifact.kind == "model",
                        Artifact.is_default.is_(True),
                    )
                )
            )
            .scalars()
            .all()
        )
        for o in others:
            o.is_default = False
    artifact.is_default = value
    await audit.record(session, actor.id, "artifact.set_default", "artifact", artifact.id, {"is_default": value})
    await session.commit()
    return artifact


async def delete(session: AsyncSession, actor: User, artifact: Artifact) -> None:
    n = (
        await session.execute(select(func.count()).select_from(Job).where(Job.artifact_id == artifact.id))
    ).scalar_one()
    if n:
        raise conflict("ARTIFACT_IN_USE", f"有 {n} 個推論任務引用此模型，請先刪除那些任務")
    storage = get_storage()
    p = storage.abs(artifact.path)
    if p.is_dir():
        storage.remove_tree(artifact.path)
    elif p.exists():
        p.unlink()
    project = await session.get(Project, artifact.project_id)
    await session.delete(artifact)
    await audit.record(session, actor.id, "artifact.delete", "artifact", artifact.id, {"path": artifact.path})
    if project:
        await projects_svc.recompute_storage(session, project)
    await session.commit()


async def register_from_job(session: AsyncSession, job: Job, body: ArtifactRegister) -> Artifact:
    """Trainer wrote a file under the job output dir; validate, size, quota, version, record."""
    storage = get_storage()
    rel = f"{job.output_path}/{body.path.lstrip('/')}"
    abs_path = storage.abs(rel)
    if not abs_path.exists():
        raise not_found("ARTIFACT_FILE_MISSING", f"檔案不存在：{body.path}")
    size = storage.usage_bytes(rel) if abs_path.is_dir() else abs_path.stat().st_size
    project = job.project
    used = storage.usage_bytes(f"projects/{project.slug}")
    quota = project.storage_quota_mb * 1024 * 1024
    if used > quota:
        if abs_path.is_dir():
            storage.remove_tree(rel)
        else:
            abs_path.unlink(missing_ok=True)
        raise conflict("STORAGE_QUOTA_EXCEEDED", f"專案儲存已達上限 {project.storage_quota_mb} MB")
    version = (
        (
            await session.execute(
                select(func.max(Artifact.version)).where(Artifact.project_id == project.id, Artifact.name == body.name)
            )
        ).scalar_one()
        or 0
    ) + 1
    art = Artifact(
        project_id=project.id,
        job_id=job.id,
        name=body.name,
        version=version,
        kind=body.kind,
        model_family=(body.metadata or {}).get("family") or job.model_family or "unknown",
        framework=body.framework,
        path=rel,
        size_bytes=size,
        metrics=body.metrics,
        metadata_=body.metadata,
        is_default=False,
    )
    session.add(art)
    await session.flush()
    if body.kind == "model" and (body.set_default or await projects_svc.default_model(session, project.id) is None):
        others = (
            (
                await session.execute(
                    select(Artifact).where(
                        Artifact.project_id == project.id, Artifact.kind == "model", Artifact.is_default.is_(True)
                    )
                )
            )
            .scalars()
            .all()
        )
        for o in others:
            o.is_default = False
        art.is_default = True
    project.storage_used_bytes = used
    await session.commit()
    return art
