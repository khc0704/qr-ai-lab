"""Jobs: creation/validation, the global queue, cancel/stop/reorder, logs, state transitions used by the scheduler."""

from __future__ import annotations

import itertools
import os
import shutil
from datetime import timedelta
from pathlib import Path
from typing import Any

import qrlab_preprocess
from sqlalchemy import func, select
from sqlalchemy import update as sql_update
from sqlalchemy.ext.asyncio import AsyncSession

from app.catalog import loader
from app.core.errors import bad_request, conflict, not_found
from app.db.base import utcnow
from app.events.bus import get_bus
from app.models import Artifact, DataSource, Job, Project, Upload, User
from app.schemas.job import JobCreate, JobInputBody
from app.schemas.settings import ResourcePool
from app.services import audit
from app.services import model_zoo as zoo_svc
from app.services import projects as projects_svc
from app.services import settings as settings_svc
from app.services import uploads as uploads_svc
from app.storage.local import get_storage

RANK_STEP = 1000


async def get(session: AsyncSession, job_id: int) -> Job:
    job = await session.get(Job, job_id)
    if job is None:
        raise not_found("JOB_NOT_FOUND", "找不到任務")
    return job


async def list_recent(
    session: AsyncSession,
    *,
    project_ids: list[int] | None,
    statuses: list[str] | None = None,
    kind: str | None = None,
    limit: int = 20,
) -> list[Job]:
    """Newest jobs across projects (project_ids=None → all projects, admin only)."""
    stmt = select(Job)
    if project_ids is not None:
        if not project_ids:
            return []
        stmt = stmt.where(Job.project_id.in_(project_ids))
    if statuses:
        stmt = stmt.where(Job.status.in_(statuses))
    if kind:
        stmt = stmt.where(Job.kind == kind)
    rows = (await session.execute(stmt.order_by(Job.created_at.desc(), Job.id.desc()).limit(limit))).scalars().all()
    return list(rows)


async def list_jobs(
    session: AsyncSession,
    *,
    project_id: int | None = None,
    created_by_id: int | None = None,
    statuses: list[str] | None = None,
    kind: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[Job], int]:
    stmt = select(Job)
    if project_id:
        stmt = stmt.where(Job.project_id == project_id)
    if created_by_id:
        stmt = stmt.where(Job.created_by_id == created_by_id)
    if statuses:
        stmt = stmt.where(Job.status.in_(statuses))
    if kind:
        stmt = stmt.where(Job.kind == kind)
    total = (await session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (
        (
            await session.execute(
                stmt.order_by(Job.created_at.desc(), Job.id.desc()).offset((page - 1) * page_size).limit(page_size)
            )
        )
        .scalars()
        .all()
    )
    return list(rows), total


async def queue(session: AsyncSession) -> tuple[list[Job], list[Job]]:
    running = list(
        (
            await session.execute(
                select(Job).where(Job.status.in_(("scheduled", "running"))).order_by(Job.started_at, Job.id)
            )
        )
        .scalars()
        .all()
    )
    queued = list(
        (
            await session.execute(
                select(Job).where(Job.status == "queued").order_by(Job.queue_rank, Job.created_at, Job.id)
            )
        )
        .scalars()
        .all()
    )
    return running, queued


async def queue_positions(session: AsyncSession) -> dict[int, int]:
    _, queued = await queue(session)
    return {j.id: i + 1 for i, j in enumerate(queued)}


def wait_reason(
    job: Job, pool: ResourcePool, allocated: dict[str, float], per_project: dict[int, dict[str, float]]
) -> str | None:
    """Why a queued job is not running right now (informational; the scheduler re-evaluates each tick)."""
    p = job.project
    pu = per_project.get(p.id, {"gpu": 0, "cpu": 0, "memory_mb": 0, "running_jobs": 0})
    if pu["running_jobs"] >= p.max_concurrent_jobs:
        return f"專案已達同時執行上限（{int(pu['running_jobs'])}/{p.max_concurrent_jobs}）"
    if pu["gpu"] + job.requested_gpu > p.gpu_limit:
        return f"專案 GPU 配額不足（{int(pu['gpu'])}/{p.gpu_limit}）"
    if pu["cpu"] + float(job.requested_cpu) > float(p.cpu_limit):
        return f"專案 CPU 配額不足（{pu['cpu']:g}/{float(p.cpu_limit):g}）"
    if pu["memory_mb"] + job.requested_memory_mb > p.memory_limit_mb:
        return "專案記憶體配額不足"
    if allocated["running_jobs"] >= pool.max_running_jobs:
        return f"資源池已達同時執行上限（{int(allocated['running_jobs'])}/{pool.max_running_jobs}）"
    free_gpu = len(pool.gpu_indices) - allocated["gpu"]
    if job.requested_gpu > free_gpu:
        return f"等待 {job.requested_gpu} GPU（資源池 {int(free_gpu)}/{len(pool.gpu_indices)} 可用）"
    if float(job.requested_cpu) > pool.cpu_cores - allocated["cpu"]:
        return "等待 CPU（資源池不足）"
    if job.requested_memory_mb > pool.memory_mb - allocated["memory_mb"]:
        return "等待記憶體（資源池不足）"
    return None


async def _next_rank(session: AsyncSession) -> int:
    mx = (await session.execute(select(func.max(Job.queue_rank)).where(Job.status == "queued"))).scalar_one()
    return (mx or 0) + RANK_STEP


async def create(session: AsyncSession, actor: User, project: Project, body: JobCreate) -> Job:
    if project.status != "active":
        raise conflict("PROJECT_ARCHIVED", "專案已封存")
    if (
        body.requested_gpu > project.gpu_limit
        or float(body.requested_cpu) > float(project.cpu_limit)
        or body.requested_memory_mb > project.memory_limit_mb
    ):
        quota = f"{project.gpu_limit} GPU · {float(project.cpu_limit):g} CPU · {project.memory_limit_mb} MB"
        raise bad_request("QUOTA_EXCEEDED", f"資源請求超過專案配額（{quota}）")
    defaults = await settings_svc.get_job_defaults(session)
    timeout = body.timeout_minutes or project.default_job_timeout_minutes or defaults.timeout_minutes

    task_type = body.task_type or project.task_type
    model_family = body.model_family
    mode = body.mode
    config: dict[str, Any] = dict(body.config or {})
    artifact: Artifact | None = None

    if body.kind == "train":
        mode = mode or "auto"
        if mode == "manual":
            if not model_family:
                raise bad_request("MODEL_FAMILY_REQUIRED", "手動模式需要指定 model_family")
            if not loader.supports(model_family, project.data_type, task_type):
                raise bad_request("MODEL_NOT_SUPPORTED", f"{model_family} 不支援 {project.data_type} × {task_type}")
            if loader.needs_gpu(model_family) and body.requested_gpu == 0:
                raise bad_request("GPU_REQUIRED", f"{model_family} 需要至少 1 GPU")
            if not zoo_svc.family_ready(model_family):
                raise bad_request(
                    "WEIGHTS_MISSING", f"{model_family} 需要的預訓練權重尚未匯入模型庫，請管理員在「模型庫」頁匯入"
                )
        else:
            try:
                search = loader.automl_search(project.data_type, task_type, body.input.spec)
            except ValueError as e:
                raise bad_request("AUTOML_NOT_AVAILABLE", str(e)) from e
            if body.config and body.config.get("search"):
                search = {**search, **body.config["search"]}
            if body.requested_gpu == 0:
                search["candidates"] = [c for c in search["candidates"] if not loader.needs_gpu(c)]
                if not search["candidates"]:
                    raise bad_request("GPU_REQUIRED", "所有候選模型都需要 GPU，請申請至少 1 GPU")
            ready = zoo_svc.families_ready()
            missing = [c for c in search["candidates"] if not ready.get(c, True)]
            if missing:
                search["candidates"] = [c for c in search["candidates"] if c not in missing]
                search["skipped_missing_weights"] = missing
                if not search["candidates"]:
                    raise bad_request("WEIGHTS_MISSING", f"候選模型 {missing} 的預訓練權重都不在模型庫，請管理員先匯入")
            config["search"] = search
            model_family = None
        if body.input.kind == "inline":
            raise bad_request("INLINE_NOT_FOR_TRAIN", "訓練不能用直接輸入")
    else:
        if not body.artifact_id:
            raise bad_request("ARTIFACT_REQUIRED", "推論需要指定模型")
        artifact = await session.get(Artifact, body.artifact_id)
        if artifact is None or artifact.project_id != project.id or artifact.kind != "model":
            raise not_found("ARTIFACT_NOT_FOUND", "找不到模型")
        model_family = artifact.model_family
        task_type = (artifact.metadata_ or {}).get("task_type") or task_type
        mode = None
        if loader.needs_gpu(model_family) and body.requested_gpu == 0:
            raise bad_request("GPU_REQUIRED", f"{model_family} 需要至少 1 GPU")
        if not zoo_svc.family_ready(model_family):
            raise bad_request("WEIGHTS_MISSING", f"{model_family} 推論需要的預訓練權重不在模型庫，請管理員先匯入")

    steps = body.input.spec.get("preprocess")
    if steps:
        if artifact is not None and (artifact.metadata_ or {}).get("preprocess"):
            raise bad_request(
                "PREPROCESS_FIXED_BY_MODEL", "此模型訓練時已內含前處理，推論會自動套用相同步驟，請移除 preprocess"
            )
        try:
            qrlab_preprocess.validate(project.data_type, task_type, steps)
        except ValueError as e:
            raise bad_request("PREPROCESS_INVALID", str(e)) from e

    data_source: DataSource | None = None
    input_doc: dict[str, Any] = {"kind": body.input.kind, "format": body.input.format, "spec": body.input.spec}
    if body.input.kind == "data_source":
        if not body.input.data_source_id:
            raise bad_request("DATA_SOURCE_REQUIRED", "請選擇資料來源")
        data_source = await session.get(DataSource, body.input.data_source_id)
        if data_source is None or data_source.project_id != project.id:
            raise not_found("DATA_SOURCE_NOT_FOUND", "找不到資料來源")
        input_doc["format"] = body.input.format or data_source.format
        input_doc["data_source_name"] = data_source.name
        input_doc["spec"] = {**(data_source.default_spec or {}), **body.input.spec}
    elif body.input.kind == "upload":
        if not body.input.upload_id:
            raise bad_request("UPLOAD_REQUIRED", "請先上傳檔案")
    elif body.input.kind == "inline":
        if not body.input.rows:
            raise bad_request("ROWS_REQUIRED", "直接輸入需要 rows")
        input_doc["rows"] = body.input.rows
        input_doc["format"] = "json"

    job = Job(
        project_id=project.id,
        kind=body.kind,
        name=body.name,
        status="queued",
        queue_rank=await _next_rank(session),
        requested_gpu=body.requested_gpu,
        requested_cpu=body.requested_cpu,
        requested_memory_mb=body.requested_memory_mb,
        requested_gpu_memory_mb=body.requested_gpu_memory_mb if body.requested_gpu > 0 else None,
        timeout_minutes=timeout,
        task_type=task_type,
        mode=mode,
        model_family=model_family,
        data_source_id=data_source.id if data_source else None,
        artifact_id=artifact.id if artifact else None,
        input=input_doc,
        config=config or None,
        created_by_id=actor.id,
    )
    session.add(job)
    await session.flush()
    storage = get_storage()
    job.output_path = f"projects/{project.slug}/jobs/{job.id}"
    job.log_path = f"{job.output_path}/logs/job.log"
    if body.input.kind == "upload":
        up = await uploads_svc.get(session, project, body.input.upload_id)  # type: ignore[arg-type]
        dst = uploads_svc.claim(up, job)
        detected = dict(up.detected_spec or {})
        sha256 = detected.pop("sha256", None)
        input_doc = {
            **input_doc,
            "format": body.input.format or up.format,
            "original_filename": up.original_filename,
            "size_bytes": up.size_bytes,
            "file": dst.name,
            "spec": {**detected, **body.input.spec},
            # reproducibility: the upload is deleted when the job ends, the fingerprint is kept
            "fingerprint": {
                "sha256": sha256,
                "size_bytes": up.size_bytes,
                **{k: detected[k] for k in ("row_count", "image_count") if k in detected},
            },
        }
        job.input = input_doc
    storage.ensure(storage.job_dir(project.slug, job.id) / "logs")
    await session.commit()
    await get_bus().publish(job.id, "status", {"status": "queued", "queue_rank": job.queue_rank})
    return await get(session, job.id)


TOOL_KINDS = ("preprocess", "analysis")


async def create_tool_job(
    session: AsyncSession,
    actor: User,
    project: Project,
    *,
    kind: str,
    name: str,
    data_type: str,
    src_file: Path,
    original_filename: str,
    fmt: str,
    spec: dict[str, Any],
    config: dict[str, Any],
    requested_gpu: int = 0,
    requested_cpu: float | None = None,
    requested_memory_mb: int | None = None,
    requested_gpu_memory_mb: int | None = None,
    timeout_minutes: int | None = None,
) -> Job:
    """A preprocessing / analysis job in the shared tool pool. The uploaded file is moved into the job's input dir
    (deleted when the job ends, like every upload); resources default to the pool quota."""
    if kind not in TOOL_KINDS:
        raise bad_request("BAD_JOB_KIND", f"未知的工具任務 {kind}")
    if project.status != "active":
        raise conflict("PROJECT_ARCHIVED", "工具池已停用")
    defaults = await settings_svc.get_job_defaults(session)
    cpu = min(float(project.cpu_limit), requested_cpu or min(2.0, float(project.cpu_limit)))
    mem = min(project.memory_limit_mb, requested_memory_mb or min(4096, project.memory_limit_mb))
    gpu = min(project.gpu_limit, requested_gpu)
    job = Job(
        project_id=project.id,
        kind=kind,
        name=name[:120],
        status="queued",
        queue_rank=await _next_rank(session),
        requested_gpu=gpu,
        requested_cpu=cpu,
        requested_memory_mb=mem,
        requested_gpu_memory_mb=requested_gpu_memory_mb if gpu > 0 else None,
        timeout_minutes=timeout_minutes or project.default_job_timeout_minutes or defaults.timeout_minutes,
        task_type=None,
        mode=None,
        model_family=None,
        input={"kind": "upload", "format": fmt, "spec": spec, "data_type": data_type, "tool": True},
        config=config or None,
        created_by_id=actor.id,
    )
    session.add(job)
    await session.flush()
    storage = get_storage()
    job.output_path = f"projects/{project.slug}/jobs/{job.id}"
    job.log_path = f"{job.output_path}/logs/job.log"
    dst_dir = storage.ensure(storage.job_input_dir(job.id))
    dst = dst_dir / f"data{src_file.suffix.lower()}"
    shutil.move(str(src_file), str(dst))
    job.input = {
        **job.input,
        "original_filename": original_filename[:255],
        "size_bytes": dst.stat().st_size,
        "file": dst.name,
    }
    storage.ensure(storage.job_dir(project.slug, job.id) / "logs")
    await session.commit()
    await get_bus().publish(job.id, "status", {"status": "queued", "queue_rank": job.queue_rank})
    return await get(session, job.id)


def output_file(job: Job) -> Path | None:
    rel = (job.result or {}).get("output_path")
    if not rel:
        return None
    p = get_storage().abs(rel)
    return p if p.is_file() else None


async def mark_output_downloaded(job_id: int) -> None:
    """Tool results are handed over once: after the download the file is removed and the job remembers it."""
    from app.db.session import get_sessionmaker

    async with get_sessionmaker()() as session:
        job = await session.get(Job, job_id)
        if job is None:
            return
        p = output_file(job)
        if p is not None:
            p.unlink(missing_ok=True)
        job.result = {**(job.result or {}), "downloaded_at": utcnow().isoformat()}
        await projects_svc.recompute_storage(session, job.project)
        await session.commit()


async def expire_tool_outputs(session: AsyncSession, ttl_hours: int) -> int:
    """Preprocessing results nobody downloaded are deleted after ttl_hours (the job row and log stay)."""
    cutoff = utcnow() - timedelta(hours=ttl_hours)
    rows = (
        (
            await session.execute(
                select(Job).where(
                    Job.kind == "preprocess",
                    Job.status.in_(("succeeded", "failed", "cancelled")),
                    Job.finished_at < cutoff,
                )
            )
        )
        .scalars()
        .all()
    )
    n = 0
    for job in rows:
        p = output_file(job)
        if p is None or (job.result or {}).get("expired_at"):
            continue
        p.unlink(missing_ok=True)
        job.result = {**(job.result or {}), "expired_at": utcnow().isoformat()}
        await projects_svc.recompute_storage(session, job.project)
        n += 1
    if n:
        await session.commit()
    return n


async def cancel(
    session: AsyncSession, actor: User, job: Job, reason: str | None = None, *, forced: bool = False
) -> Job:
    if not job.is_active:
        raise conflict("JOB_NOT_ACTIVE", f"任務已是 {job.status}")
    action = "job.stop" if forced else "job.cancel"
    await audit.record(session, actor.id, action, "job", job.id, {"reason": reason, "status": job.status})
    if job.status == "queued":
        # Claim the row atomically: the scheduler may be launching this very job (see mark_scheduled).
        res = await session.execute(
            sql_update(Job).where(Job.id == job.id, Job.status == "queued").values(status="cancelled")
        )
        if res.rowcount == 1:
            job.status = "cancelled"
            await finish(session, job, "cancelled", cancel_reason=reason, actor=actor)
            return job
        await session.refresh(job)  # it got scheduled meanwhile: fall through to a stop request
    job.cancel_requested_at = utcnow()
    job.cancel_requested_by_id = actor.id
    job.cancel_requested_by = actor
    job.cancel_reason = reason
    await session.commit()
    await get_bus().publish(
        job.id,
        "log",
        {
            "level": "SYSTEM",
            "text": f"{'admin ' if forced else ''}{actor.display_name or actor.username} requested stop"
            + (f": {reason}" if reason else ""),
        },
    )
    return job


async def restart(session: AsyncSession, actor: User, job: Job) -> Job:
    """Re-queue a finished job as a new job with the same input, resources and settings (audit: job.restart).
    One-time uploads are deleted when a job ends, so those jobs cannot be restarted."""
    if job.is_active:
        raise conflict("JOB_ACTIVE", f"任務仍在 {job.status}，請先中斷")
    if job.project.status != "active":
        raise conflict("PROJECT_ARCHIVED", "專案已封存")
    inp = job.input or {}
    if inp.get("kind") == "upload":
        raise conflict("RESTART_INPUT_GONE", "一次性上傳的資料在任務結束時已刪除，請用「複製設定」重新上傳")
    config = dict(job.config or {})
    if job.mode == "auto" and isinstance(config.get("search"), dict):
        # candidates / skipped weights are recomputed from the catalog and the model zoo at creation time
        config["search"] = {
            k: v for k, v in config["search"].items() if k not in ("candidates", "skipped_missing_weights")
        }
    config["restarted_from"] = job.id
    body = JobCreate(
        kind=job.kind,  # type: ignore[arg-type]
        name=job.name,
        input=JobInputBody(
            kind=inp.get("kind", "data_source"),
            data_source_id=job.data_source_id,
            format=inp.get("format"),
            spec=dict(inp.get("spec") or {}),
            rows=inp.get("rows"),
        ),
        task_type=job.task_type,
        mode=job.mode,  # type: ignore[arg-type]
        model_family=job.model_family if job.mode != "auto" else None,
        config=config,
        artifact_id=job.artifact_id,
        requested_gpu=job.requested_gpu,
        requested_cpu=float(job.requested_cpu),
        requested_memory_mb=job.requested_memory_mb,
        requested_gpu_memory_mb=job.requested_gpu_memory_mb,
        timeout_minutes=job.timeout_minutes,
    )
    new = await create(session, actor, job.project, body)
    await audit.record(session, actor.id, "job.restart", "job", new.id, {"from_job_id": job.id})
    await session.commit()
    return await get(session, new.id)


async def set_order(session: AsyncSession, admin: User, job_ids: list[int]) -> list[Job]:
    _, queued = await queue(session)
    by_id = {j.id: j for j in queued}
    unknown = [i for i in job_ids if i not in by_id]
    if unknown:
        raise bad_request("JOB_NOT_QUEUED", f"不在佇列中：{unknown}")
    ordered = [by_id[i] for i in job_ids] + [j for j in queued if j.id not in set(job_ids)]
    for i, j in enumerate(ordered):
        j.queue_rank = (i + 1) * RANK_STEP
    await audit.record(session, admin.id, "queue.reorder", "job", None, {"order": [j.id for j in ordered]})
    await session.commit()
    return ordered


async def move(session: AsyncSession, admin: User, job: Job, position: str) -> list[Job]:
    _, queued = await queue(session)
    ids = [j.id for j in queued]
    if job.id not in ids:
        raise bad_request("JOB_NOT_QUEUED", "任務不在佇列中")
    i = ids.index(job.id)
    ids.pop(i)
    target = {"top": 0, "bottom": len(ids), "up": max(0, i - 1), "down": min(len(ids), i + 1)}[position]
    ids.insert(target, job.id)
    return await set_order(session, admin, ids)


async def delete(session: AsyncSession, admin: User, job: Job) -> None:
    if job.is_active:
        raise conflict("JOB_ACTIVE", "請先取消或中斷任務")
    n_art = (
        await session.execute(select(func.count()).select_from(Artifact).where(Artifact.job_id == job.id))
    ).scalar_one()
    if n_art:
        raise conflict("JOB_HAS_ARTIFACTS", "請先刪除此任務的產物")
    storage = get_storage()
    if job.output_path:
        storage.remove_tree(job.output_path)
    storage.remove_tree(f"jobs/{job.id}")
    await audit.record(session, admin.id, "job.delete", "job", job.id, {"project_id": job.project_id})
    project = job.project
    await session.execute(sql_update(Upload).where(Upload.claimed_by_job_id == job.id).values(claimed_by_job_id=None))
    await session.delete(job)
    await projects_svc.recompute_storage(session, project)
    await session.commit()


# --- state transitions (scheduler) ----------------------------------------------------------


class JobStateChanged(Exception):
    """The job left the expected state while the scheduler was deciding (e.g. cancelled from the API)."""


async def mark_scheduled(session: AsyncSession, job: Job, gpus: list[int], cpus: list[int] | None = None) -> None:
    res = await session.execute(
        sql_update(Job)
        .where(Job.id == job.id, Job.status == "queued")
        .values(status="scheduled", assigned_gpus=gpus, assigned_cpus=cpus or None)
    )
    if res.rowcount != 1:
        await session.rollback()
        await session.refresh(job)
        raise JobStateChanged(f"job {job.id} is {job.status}, not queued")
    job.status = "scheduled"
    job.assigned_gpus = gpus
    job.assigned_cpus = cpus or None
    await session.commit()
    await get_bus().publish(
        job.id, "status", {"status": "scheduled", "assigned_gpus": gpus, "assigned_cpus": cpus or []}
    )


async def mark_running(session: AsyncSession, job: Job, container_id: str | None) -> None:
    job.status = "running"
    job.container_id = container_id
    job.started_at = utcnow()
    await session.commit()
    await get_bus().publish(job.id, "status", {"status": "running"})


async def finish(
    session: AsyncSession,
    job: Job,
    status: str,
    *,
    error: str | None = None,
    cancel_reason: str | None = None,
    actor: User | None = None,
) -> None:
    job.status = status
    job.finished_at = utcnow()
    if error:
        job.error_message = error[:4000]
    if cancel_reason and not job.cancel_reason:
        job.cancel_reason = cancel_reason
    if actor and status == "cancelled":
        job.cancel_requested_at = job.cancel_requested_at or utcnow()
        if job.cancel_requested_by_id is None:
            job.cancel_requested_by_id = actor.id
            job.cancel_requested_by = actor
    storage = get_storage()
    storage.remove_tree(f"jobs/{job.id}")  # never keep user input after a job ends
    if job.output_path:
        storage.remove_tree(f"{job.output_path}/_work")  # trainer scratch (extracted zips etc.)
    await projects_svc.recompute_storage(session, job.project)
    if status != "succeeded":
        await audit.record(
            session,
            actor.id if actor else None,
            f"job.{status}",
            "job",
            job.id,
            {"error": error, "reason": cancel_reason},
        )
    await session.commit()
    bus = get_bus()
    await bus.publish(job.id, "status", {"status": status, "error": error, "cancel_reason": job.cancel_reason})
    await bus.publish(job.id, "end", {"status": status})


def deadline(job: Job):
    return (job.started_at or job.created_at) + timedelta(minutes=job.timeout_minutes)


# --- logs -------------------------------------------------------------------------------------


def log_file(job: Job) -> Path:
    return get_storage().abs(job.log_path or f"projects/{job.project.slug}/jobs/{job.id}/logs/job.log")


def _count_lines(path: Path) -> int:
    n = 0
    last = b""
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            n += chunk.count(b"\n")
            last = chunk[-1:] if chunk else last
    return n + (1 if last and last != b"\n" else 0)


def _tail_lines(path: Path, limit: int) -> list[str]:
    """Last ``limit`` lines read backwards in blocks (a 50 MB log is never loaded whole for a tail)."""
    with path.open("rb") as f:
        f.seek(0, os.SEEK_END)
        pos = f.tell()
        buf = b""
        while pos > 0 and buf.count(b"\n") <= limit:
            step = min(1 << 16, pos)
            pos -= step
            f.seek(pos)
            buf = f.read(step) + buf
    lines = buf.decode("utf-8", errors="replace").splitlines()
    return lines[-limit:]


def read_log(job: Job, offset: int | None, limit: int = 500) -> tuple[list[str], int, int]:
    """Returns (lines, offset, total). offset=None → tail. Reads in blocks; call via ``asyncio.to_thread``."""
    path = log_file(job)
    if not path.exists():
        return [], 0, 0
    total = _count_lines(path)
    if offset is None:
        lines = _tail_lines(path, limit)
        return lines, max(0, total - len(lines)), total
    start = max(0, min(offset, total))
    with path.open("r", encoding="utf-8", errors="replace") as f:
        lines = [line.rstrip("\r\n") for line in itertools.islice(f, start, start + limit)]
    return lines, start, total


def append_log(job: Job, level: str, text: str, max_mb: int = 50) -> str:
    path = log_file(job)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.stat().st_size > max_mb * 1024 * 1024:
        os.replace(path, path.with_suffix(".log.1"))
    line = f"{utcnow().isoformat(timespec='milliseconds')}Z [{level}] {text}"
    with path.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
    return line
