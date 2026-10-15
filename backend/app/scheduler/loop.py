"""The scheduler: one global queue, resource pool as the hard capacity, hardened job containers.

Tick: reconcile running jobs → launch queued jobs that fit → (hourly) cleanup. See docs/ARCHITECTURE.md §6.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import re
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.core.security import create_job_token
from app.db.base import utcnow
from app.db.session import get_sessionmaker
from app.events.bus import get_bus
from app.models import Artifact, DataSource, Job
from app.scheduler.runner import DockerRunner, LaunchSpec, Runner, SubprocessRunner
from app.services import data_sources as ds_svc
from app.services import jobs as jobs_svc
from app.services import node as node_svc
from app.services import projects as projects_svc
from app.services import settings as settings_svc
from app.services import uploads as uploads_svc
from app.storage.local import get_storage

log = get_logger("scheduler")
LEVEL_RE = re.compile(r"^\[(INFO|WARN|WARNING|ERROR|DEBUG|SYSTEM)\]\s?(.*)$")


@dataclass
class ActiveJob:
    handle: str
    log_task: asyncio.Task | None
    log_path: Path
    timed_out: bool = False
    stopping: bool = False


def make_runner(settings: Settings) -> Runner:
    if settings.job_runner == "docker":
        return DockerRunner()
    return SubprocessRunner(settings.trainer_dir)


class Scheduler:
    def __init__(self, runner: Runner | None = None, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.runner: Runner = runner or make_runner(self.settings)
        self.active: dict[int, ActiveJob] = {}
        self._ticks = 0

    # --- lifecycle ---------------------------------------------------------------------------

    async def run_forever(self) -> None:
        log.info("scheduler started", runner=type(self.runner).__name__, interval=self.settings.scheduler_interval_s)
        while True:
            try:
                await self.tick()
            except Exception as e:
                log.error("tick failed", error=repr(e))
            await asyncio.sleep(self.settings.scheduler_interval_s)

    async def tick(self) -> None:
        self._ticks += 1
        async with get_sessionmaker()() as session:
            await self.reconcile(session)
            await self.schedule(session)
            if self._ticks % max(1, int(3600 / max(self.settings.scheduler_interval_s, 1))) == 1:
                await self.cleanup(session)

    # --- log pump ----------------------------------------------------------------------------

    def _write_log(self, path: Path, level: str, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        max_bytes = self.settings.log_max_mb * 1024 * 1024
        if path.exists() and path.stat().st_size > max_bytes:
            path.replace(path.with_suffix(".log.1"))
        with path.open("a", encoding="utf-8") as f:
            f.write(f"{utcnow().isoformat(timespec='milliseconds')}Z [{level}] {text}\n")

    async def _system(self, job_id: int, path: Path, text: str) -> None:
        self._write_log(path, "SYSTEM", text)
        await get_bus().publish(job_id, "log", {"level": "SYSTEM", "text": text})

    async def _pump_logs(self, job_id: int, handle: str, path: Path) -> None:
        bus = get_bus()
        try:
            async for line in self.runner.logs(handle):
                m = LEVEL_RE.match(line)
                level, text = (m.group(1), m.group(2)) if m else ("INFO", line)
                level = "WARN" if level == "WARNING" else level
                self._write_log(path, level, text)
                await bus.publish(job_id, "log", {"level": level, "text": text})
        except Exception as e:
            self._write_log(path, "ERROR", f"log pump failed: {e!r}")

    # --- reconcile ---------------------------------------------------------------------------

    async def reconcile(self, session: AsyncSession) -> None:
        rows = (await session.execute(select(Job).where(Job.status.in_(("scheduled", "running"))))).scalars().all()
        for job in rows:
            active = self.active.get(job.id)
            log_path = get_storage().abs(job.log_path) if job.log_path else jobs_svc.log_file(job)
            if active is None:
                handle = await self.runner.find(job.id) if job.container_id else None
                if handle is None:
                    await self._system(job.id, log_path, "scheduler restarted and lost track of this job")
                    await jobs_svc.finish(session, job, "failed", error="scheduler restarted while the job was running")
                    continue
                pump = asyncio.create_task(self._pump_logs(job.id, handle, log_path))
                active = ActiveJob(handle=handle, log_task=pump, log_path=log_path)
                self.active[job.id] = active
            state = await self.runner.inspect(active.handle)
            if state.running:
                if job.cancel_requested_at and not active.stopping:
                    active.stopping = True
                    await self._system(job.id, log_path, "docker stop (grace 10s)")
                    await self.runner.stop(active.handle, grace=10)
                elif utcnow() > jobs_svc.deadline(job) and not active.stopping:
                    active.stopping = True
                    active.timed_out = True
                    await self._system(job.id, log_path, f"timeout after {job.timeout_minutes} minutes, stopping")
                    await self.runner.stop(active.handle, grace=10)
                continue
            # exited
            if active.log_task:
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(active.log_task, timeout=30)
            trainer_status = (job.metrics or {}).get("_trainer_status")
            if job.cancel_requested_at:
                status, error = "cancelled", None
            elif active.timed_out:
                status, error = "failed", f"timeout after {job.timeout_minutes} minutes"
            elif state.exit_code == 0 and trainer_status == "succeeded":
                status, error = "succeeded", None
            else:
                tail = jobs_svc.read_log(job, None, 20)[0]
                error = job.error_message or f"exit code {state.exit_code}; last log: " + " | ".join(tail[-5:])[:1500]
                status = "failed"
            await self._system(job.id, log_path, f"container exited {state.exit_code} → {status}")
            await jobs_svc.finish(session, job, status, error=error)
            await self.runner.remove(active.handle)
            self.active.pop(job.id, None)
            log.info("job finished", job_id=job.id, status=status)

    # --- schedule ----------------------------------------------------------------------------

    async def schedule(self, session: AsyncSession) -> None:
        pool = await settings_svc.get_resource_pool(session)
        alloc = await node_svc.allocated(session)
        if alloc.running_jobs >= pool.max_running_jobs:
            return
        used_gpus = set((await node_svc.gpu_job_map(session)).keys())
        free_gpus = [g for g in pool.gpu_indices if g not in used_gpus]
        free_cpu = pool.cpu_cores - alloc.cpu
        free_mem = pool.memory_mb - alloc.memory_mb
        slots = pool.max_running_jobs - alloc.running_jobs
        stmt = select(Job).where(Job.status == "queued").order_by(Job.queue_rank, Job.created_at, Job.id).limit(50)
        queued = (await session.execute(stmt)).scalars().all()
        if not queued:
            return
        usage = await projects_svc.usage_map(session, list({j.project_id for j in queued}))
        per_project = {pid: u.model_dump() for pid, u in usage.items()}
        launched_projects: set[int] = set()
        for job in queued:
            if slots <= 0:
                break
            p = job.project
            pu = per_project[p.id]
            fits_project = (
                pu["running_jobs"] < p.max_concurrent_jobs
                and pu["gpu"] + job.requested_gpu <= p.gpu_limit
                and pu["cpu"] + float(job.requested_cpu) <= float(p.cpu_limit)
                and pu["memory_mb"] + job.requested_memory_mb <= p.memory_limit_mb
                and p.storage_used_bytes < p.storage_quota_mb * 1024 * 1024
                and p.status == "active"
            )
            fits_pool = (
                job.requested_gpu <= len(free_gpus)
                and float(job.requested_cpu) <= free_cpu
                and job.requested_memory_mb <= free_mem
            )
            if not (fits_project and fits_pool) or p.id in launched_projects:
                if not pool.allow_backfill:
                    break
                continue
            gpus = free_gpus[: job.requested_gpu]
            try:
                await self.launch(session, job, gpus)
            except Exception as e:
                log.error("launch failed", job_id=job.id, error=repr(e))
                await self._system(job.id, jobs_svc.log_file(job), f"launch failed: {e!r}")
                await jobs_svc.finish(session, job, "failed", error=f"launch failed: {e!r}"[:1000])
                continue
            free_gpus = free_gpus[job.requested_gpu :]
            free_cpu -= float(job.requested_cpu)
            free_mem -= job.requested_memory_mb
            slots -= 1
            pu["running_jobs"] += 1
            pu["gpu"] += job.requested_gpu
            pu["cpu"] += float(job.requested_cpu)
            pu["memory_mb"] += job.requested_memory_mb
            launched_projects.add(p.id)

    async def launch(self, session: AsyncSession, job: Job, gpus: list[int]) -> None:
        s = self.settings
        storage = get_storage()
        project = job.project
        input_dir = storage.ensure(storage.job_input_dir(job.id))
        output_dir = storage.ensure(storage.job_dir(project.slug, job.id))
        storage.ensure(output_dir / "logs")
        log_path = output_dir / "logs" / "job.log"
        host_root = (s.data_root_host or s.data_root).resolve()
        to_host = lambda p: host_root / p.resolve().relative_to(storage.root)  # noqa: E731

        env: dict[str, str] = {
            "JOB_ID": str(job.id),
            "JOB_KIND": job.kind,
            "JOB_TOKEN": create_job_token(job.id, job.kind, job.timeout_minutes * 60 + 900, s),
            "BACKEND_URL": s.internal_backend_url,
            "CUDA_VISIBLE_DEVICES": ",".join(str(g) for g in gpus) if gpus else "",
            "OMP_NUM_THREADS": str(max(1, int(float(job.requested_cpu)))),
            # offline by policy: weights come from the model zoo only
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "HF_DATASETS_OFFLINE": "1",
            "YOLO_OFFLINE": "1",
            "NO_PROXY": "*",
        }
        model_dir: Path | None = None
        if job.data_source_id:
            ds = await session.get(DataSource, job.data_source_id)
            if ds is not None:
                creds = ds_svc.credentials(ds)
                env.update(
                    {
                        "DATA_SOURCE_KIND": ds.kind,
                        "DATA_SOURCE_ENDPOINT": ds.endpoint or "",
                        "DATA_SOURCE_BUCKET": ds.bucket or "",
                        "DATA_SOURCE_OBJECT_PATH": ds.object_path or "",
                        "DATA_SOURCE_URL": ds.url or "",
                        "DATA_SOURCE_FORMAT": ds.format,
                        "DATA_SOURCE_ACCESS_KEY": creds.get("access_key") or "",
                        "DATA_SOURCE_SECRET_KEY": creds.get("secret_key") or "",
                        "DATA_SOURCE_REGION": creds.get("region") or "",
                        "DATA_SOURCE_HEADERS": json.dumps(creds.get("headers") or {}),
                    }
                )
                env["NO_PROXY"] = ""  # the job may need the proxy to reach the user's storage
        if job.artifact_id:
            art = await session.get(Artifact, job.artifact_id)
            if art is not None:
                model_dir = storage.abs(art.path).parent
        zoo_dir = s.zoo_root.resolve() if s.zoo_root.exists() else None
        host_zoo_dir: Path | None = None
        if zoo_dir is not None:
            inside_data_root = zoo_dir.is_relative_to(storage.root)
            host_zoo_dir = to_host(zoo_dir) if (s.data_root_host and inside_data_root) else zoo_dir
        spec = LaunchSpec(
            job_id=job.id,
            kind=job.kind,
            image=s.trainer_image,
            env=env,
            input_dir=input_dir,
            output_dir=output_dir,
            model_dir=model_dir,
            zoo_dir=zoo_dir,
            host_input_dir=to_host(input_dir),
            host_output_dir=to_host(output_dir),
            host_model_dir=to_host(model_dir) if model_dir else None,
            host_zoo_dir=host_zoo_dir,
            gpus=gpus,
            cpu=float(job.requested_cpu),
            memory_mb=job.requested_memory_mb,
            network=s.job_network if s.job_runner == "docker" else None,
            input_writable=job.data_source_id is not None,
        )
        runner_name = type(self.runner).__name__
        await jobs_svc.mark_scheduled(session, job, gpus)
        await self._system(
            job.id,
            log_path,
            f"scheduled on GPU {gpus or '[]'}, cpu={spec.cpu:g}, memory={spec.memory_mb}MB, runner={runner_name}",
        )
        handle = await self.runner.start(spec)
        await jobs_svc.mark_running(session, job, handle)
        image = s.trainer_image if s.job_runner == "docker" else "local trainer"
        await self._system(job.id, log_path, f"started ({handle[:12]}), image={image}")
        pump = asyncio.create_task(self._pump_logs(job.id, handle, log_path))
        self.active[job.id] = ActiveJob(handle=handle, log_task=pump, log_path=log_path)
        log.info("job launched", job_id=job.id, gpus=gpus, handle=handle)

    # --- cleanup -----------------------------------------------------------------------------

    async def cleanup(self, session: AsyncSession) -> None:
        purged = await uploads_svc.purge_expired(session)
        storage = get_storage()
        jobs_root = storage.abs("jobs")
        removed = 0
        if jobs_root.exists():
            stmt = select(Job.id).where(Job.status.in_(("succeeded", "failed", "cancelled")))
            terminal = set((await session.execute(stmt)).scalars().all())
            stale_before = (utcnow() - timedelta(days=2)).timestamp()
            for d in jobs_root.iterdir():
                if not (d.is_dir() and d.name.isdigit()):
                    continue
                job_id = int(d.name)
                stale = d.stat().st_mtime < stale_before and job_id not in self.active
                if job_id in terminal or stale:
                    storage.remove_tree(f"jobs/{d.name}")
                    removed += 1
        if purged or removed:
            log.info("cleanup", purged_uploads=purged, removed_input_dirs=removed)
