"""Trainer-facing operations: job spec, status/progress, metrics, result."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.catalog import loader
from app.core.errors import bad_request
from app.events.bus import get_bus
from app.models import Artifact, Job
from app.schemas.internal import ArtifactRef, JobSpec, MetricsBody, ResultBody, StatusBody
from app.services import jobs as jobs_svc
from app.storage.local import get_storage

CONTAINER_INPUT = "/job/input"
CONTAINER_OUTPUT = "/job/output"
CONTAINER_ZOO = "/job/zoo"


async def job_spec(session: AsyncSession, job: Job) -> JobSpec:
    project = job.project
    artifact = None
    if job.artifact_id:
        a = await session.get(Artifact, job.artifact_id)
        if a is not None:
            # the artifact lives in another job's output dir; the scheduler mounts it read-only at /job/model
            artifact = ArtifactRef(
                id=a.id,
                name=a.name,
                version=a.version,
                model_family=a.model_family,
                framework=a.framework,
                file=Path(a.path).name,
                metadata=a.metadata_,
            )
    wanted = list((job.config or {}).get("search", {}).get("candidates", [])) or (
        [job.model_family] if job.model_family else []
    )
    families = {}
    zoo: dict[str, str] = {}
    for fid in wanted:
        try:
            fam = loader.family(fid)
        except KeyError:
            continue
        families[fid] = {
            k: fam.get(k) for k in ("label", "framework", "defaults", "search_space", "inference_modes", "resources")
        }
        for w in fam.get("weights", []):
            zoo[w["id"]] = w["file"]
    return JobSpec(
        job_id=job.id,
        kind=job.kind,
        project_slug=project.slug,
        data_type=(job.input or {}).get("data_type") or project.data_type,
        task_type=job.task_type,
        mode=job.mode,
        model_family=job.model_family,
        config=job.config or {},
        input=job.input,
        artifact=artifact,
        resources={
            "gpu": job.requested_gpu,
            "cpu": float(job.requested_cpu),
            "memory_mb": job.requested_memory_mb,
            "assigned_gpus": job.assigned_gpus or [],
        },
        timeout_minutes=job.timeout_minutes,
        families=families,
        zoo_weights=zoo,
    )


async def update_status(session: AsyncSession, job: Job, body: StatusBody) -> Job:
    if body.progress is not None:
        job.progress = body.progress
    if body.stage is not None:
        job.current_stage = body.stage
    if body.status == "running" and job.status == "scheduled":
        await jobs_svc.mark_running(session, job, job.container_id)
    elif body.status in ("succeeded", "failed"):
        # the scheduler finalizes on container exit; the trainer's verdict is recorded first
        job.metrics = {**(job.metrics or {}), "_trainer_status": body.status}
        if body.status == "failed" and body.message:
            job.error_message = body.message[:4000]
    await session.commit()
    await get_bus().publish(
        job.id,
        "progress",
        {"progress": float(job.progress), "stage": job.current_stage, "status": body.status, "message": body.message},
    )
    return job


async def add_metrics(session: AsyncSession, job: Job, body: MetricsBody) -> Job:
    metrics: dict[str, Any] = dict(job.metrics or {})
    metrics.update(body.metrics)
    if body.epoch is not None:
        metrics["epoch"] = body.epoch
    if body.trial is not None:
        metrics["trial"] = body.trial
    if body.leaderboard_row:
        lb = list(metrics.get("leaderboard") or [])
        lb.append(body.leaderboard_row)
        direction = loader.task_metric(job.task_type)[1] if job.task_type else "maximize"
        lb.sort(key=lambda r: r.get("metric", 0), reverse=(direction == "maximize"))
        metrics["leaderboard"] = lb[:200]
    job.metrics = metrics
    await session.commit()
    await get_bus().publish(job.id, "metric", {"epoch": body.epoch, "trial": body.trial, "metrics": body.metrics})
    return job


def job_relpath(job: Job, rel: str) -> str:
    """``rel`` (trainer-supplied, relative to the job output dir) as a DATA_ROOT-relative path. The per-job token
    must not reach any other job's files, so ``..``, absolute paths and symlink escapes are rejected."""
    if not job.output_path:
        raise bad_request("JOB_NOT_LAUNCHED", "任務尚未分配輸出目錄")
    clean = rel.strip().lstrip("/")
    parts = PurePosixPath(clean).parts
    if not clean or PurePosixPath(clean).is_absolute() or any(part in ("..", ".") for part in parts):
        raise bad_request("INVALID_PATH", f"路徑不合法：{rel}")
    base = get_storage().abs(job.output_path).resolve()
    if not (base / clean).resolve().is_relative_to(base):
        raise bad_request("INVALID_PATH", f"路徑不在任務目錄內：{rel}")
    return f"{job.output_path}/{clean}"


async def set_result(session: AsyncSession, job: Job, body: ResultBody) -> Job:
    if body.result is not None:
        job.result = body.result
        winner = body.result.get("model_family")
        if isinstance(winner, str) and winner and job.kind == "train":
            job.model_family = winner
    if body.output_path:
        job.result = {**(job.result or {}), "output_path": job_relpath(job, body.output_path)}
    await session.commit()
    return job
