"""The scheduler: one global queue, the admin's resource pool as hard capacity, jobs as host processes.

Tick: reconcile running jobs (exit, cancel, timeout, memory / log watchdog) → launch queued jobs that fit
(pool, project quota, free GPUs with a pynvml pre-flight, free CPU cores) → (hourly) cleanup.
See docs/ARCHITECTURE.md §6.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import re
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

import psutil
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.core.security import create_job_token
from app.db.base import utcnow
from app.db.session import get_sessionmaker
from app.events.bus import get_bus
from app.models import Artifact, DataSource, Job
from app.scheduler.runner import (
    LaunchSpec,
    Runner,
    SubprocessRunner,
    SystemdRunner,
    systemd_available,
)
from app.services import data_sources as ds_svc
from app.services import gpu as gpu_svc
from app.services import jobs as jobs_svc
from app.services import node as node_svc
from app.services import projects as projects_svc
from app.services import settings as settings_svc
from app.services import tools as tools_svc
from app.services import uploads as uploads_svc
from app.services import usage as usage_svc
from app.storage.local import get_storage

log = get_logger("scheduler")
LINE_RE = re.compile(r"^(?:(\S+Z)\s+)?\[(INFO|WARN|WARNING|ERROR|DEBUG|SYSTEM)\]\s?(.*)$")
MB = 1024 * 1024
BACKFILL_HOLD_S = 600  # after this long at the head of the queue a GPU job stops being backfilled around


@dataclass
class ActiveJob:
    handle: str
    log_path: Path
    tail_task: asyncio.Task | None = None
    tail_stop: asyncio.Event | None = None
    timed_out: bool = False
    stopping: bool = False
    stop_reason: str | None = None
    memory_strikes: int = 0
    peak_memory_mb: int = 0


def make_runner(settings: Settings) -> Runner:
    kind = settings.job_runner
    if kind == "auto":
        kind = "systemd" if systemd_available(user=settings.systemd_user) else "subprocess"
    if kind == "systemd":
        return SystemdRunner(settings.trainer_dir, settings.trainer_python, user=settings.systemd_user)
    return SubprocessRunner(settings.trainer_dir, settings.trainer_python)


def pool_cores(count: int) -> list[int]:
    """The pool's CPU cores are the lowest `count` logical CPUs this process may run on."""
    try:
        allowed = sorted(os.sched_getaffinity(0))  # type: ignore[attr-defined]
    except AttributeError:
        allowed = list(range(psutil.cpu_count(logical=True) or 1))
    return allowed[: max(0, count)]


class Scheduler:
    def __init__(self, runner: Runner | None = None, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.runner: Runner = runner or make_runner(self.settings)
        self.active: dict[int, ActiveJob] = {}
        self._ticks = 0
        self._gpu_wait_logged: dict[int, float] = {}
        self._last_sample = 0.0
        self.sampling = True  # usage history (tests switch it off)

    # --- lifecycle ---------------------------------------------------------------------------

    async def run_forever(self) -> None:
        log.info(
            "scheduler started",
            runner=self.runner.kind,
            enforces=self.runner.enforcement.as_dict(),
            interval=self.settings.scheduler_interval_s,
        )
        while True:
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.error("tick failed", error=repr(e))
            await asyncio.sleep(self.settings.scheduler_interval_s)

    async def tick(self) -> None:
        self._ticks += 1
        async with get_sessionmaker()() as session:
            await self.reconcile(session)
            await self.schedule(session)
            await self.maybe_sample(session)
            if self._ticks % max(1, int(3600 / max(self.settings.scheduler_interval_s, 1))) == 1:
                await self.cleanup(session)

    async def maybe_sample(self, session: AsyncSession, *, force: bool = False) -> None:
        """Usage history: one ResourceSample every USAGE_SAMPLE_INTERVAL_S (actual CPU / memory per job process)."""
        if not self.sampling:
            return
        now = asyncio.get_running_loop().time()
        if not force and now - self._last_sample < self.settings.usage_sample_interval_s:
            return
        self._last_sample = now
        try:
            pids = {job_id: self.runner.pids(a.handle) for job_id, a in self.active.items()}
            await usage_svc.sample(session, pids)
        except Exception as e:
            log.warning("usage sample failed", error=repr(e))

    # --- job log: the trainer writes the file itself, the scheduler tails it ------------------

    def _write_log(self, path: Path, level: str, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(f"{utcnow().isoformat(timespec='milliseconds')}Z [{level}] {text}\n")

    async def _system(self, job_id: int, path: Path, text: str) -> None:
        self._write_log(path, "SYSTEM", text)
        active = self.active.get(job_id)
        if active is None or active.tail_task is None:  # no tail running → publish directly
            await get_bus().publish(job_id, "log", {"level": "SYSTEM", "text": text})

    @staticmethod
    def parse_line(line: str) -> tuple[str, str]:
        m = LINE_RE.match(line)
        if not m:
            return "INFO", line
        level = m.group(2)
        return ("WARN" if level == "WARNING" else level), m.group(3)

    async def _tail(self, job_id: int, path: Path, stop: asyncio.Event, offset: int = 0) -> None:
        """Publish every new line of the job log (including SYSTEM lines written by us) until the job is gone."""
        bus = get_bus()
        pending = b""
        while True:
            try:
                if path.exists():
                    with path.open("rb") as f:
                        f.seek(0, os.SEEK_END)
                        if f.tell() < offset:  # rotated in place (see _rotate_log): skip the rewritten tail
                            offset = f.tell()
                            pending = b""
                        f.seek(offset)
                        chunk = f.read()
                    if chunk:
                        offset += len(chunk)
                        data = pending + chunk
                        *lines, pending = data.split(b"\n")
                        for raw in lines:
                            level, text = self.parse_line(raw.decode("utf-8", errors="replace").rstrip("\r"))
                            await bus.publish(job_id, "log", {"level": level, "text": text})
            except Exception as e:  # keep tailing; a transient read error must not end the stream
                log.warning("log tail error", job_id=job_id, error=repr(e))
            if stop.is_set():
                if pending:
                    level, text = self.parse_line(pending.decode("utf-8", errors="replace"))
                    await bus.publish(job_id, "log", {"level": level, "text": text})
                return
            await asyncio.sleep(0.5)

    def _start_tail(self, job_id: int, active: ActiveJob, *, from_end: bool) -> None:
        offset = active.log_path.stat().st_size if (from_end and active.log_path.exists()) else 0
        active.tail_stop = asyncio.Event()
        active.tail_task = asyncio.create_task(self._tail(job_id, active.log_path, active.tail_stop, offset))

    async def _stop_tail(self, active: ActiveJob) -> None:
        if active.tail_stop:
            active.tail_stop.set()
        if active.tail_task:
            with contextlib.suppress(Exception):
                await asyncio.wait_for(active.tail_task, timeout=10)
        active.tail_task = None

    # --- watchdogs (what the runner cannot enforce by itself) ----------------------------------

    def _tree_memory_mb(self, handle: str) -> int:
        total = 0
        for pid in self.runner.pids(handle):
            try:
                p = psutil.Process(pid)
                try:
                    total += p.memory_full_info().pss  # proportional set size: shared pages counted once
                except (psutil.AccessDenied, AttributeError):
                    total += p.memory_info().rss
            except psutil.Error:
                continue
        return total // MB

    async def _watch(self, session: AsyncSession, job: Job, active: ActiveJob) -> bool:
        """Returns True when the job was told to stop because of a limit."""
        if active.stopping:
            return False
        if self.settings.memory_watchdog and not self.runner.enforcement.memory:
            used = self._tree_memory_mb(active.handle)
            active.peak_memory_mb = max(active.peak_memory_mb, used)
            if used > job.requested_memory_mb * 1.05:
                active.memory_strikes += 1
                if active.memory_strikes == 1:
                    await self._system(
                        job.id, active.log_path, f"memory {used} MB exceeds the grant of {job.requested_memory_mb} MB"
                    )
                elif active.memory_strikes >= 2:
                    active.stop_reason = f"memory limit exceeded: {used} MB used, {job.requested_memory_mb} MB granted"
                    await self._system(job.id, active.log_path, active.stop_reason + ", stopping")
                    active.stopping = True
                    await self.runner.stop(active.handle, grace=10)
                    return True
            else:
                active.memory_strikes = 0
        max_log = self.settings.log_max_mb * MB
        if active.log_path.exists() and active.log_path.stat().st_size > max_log:
            self._rotate_log(active.log_path, keep=max_log // 4)
            await self._system(
                job.id,
                active.log_path,
                f"log exceeded {self.settings.log_max_mb} MB: older lines dropped, last {max_log // 4 // MB} MB kept",
            )
        return False

    @staticmethod
    def _rotate_log(path: Path, keep: int) -> None:
        """Truncate the log in place, keeping its tail. The job writes with O_APPEND, so it keeps appending."""
        with path.open("rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - keep))
            tail = f.read()
        nl = tail.find(b"\n")
        tail = tail[nl + 1 :] if nl >= 0 else tail
        os.truncate(path, 0)
        with path.open("ab") as f:
            f.write(b"[log rotated: earlier lines were dropped to stay under the size limit]\n" + tail)

    # --- reconcile ---------------------------------------------------------------------------

    async def reconcile(self, session: AsyncSession) -> None:
        rows = (await session.execute(select(Job).where(Job.status.in_(("scheduled", "running"))))).scalars().all()
        for job in rows:
            active = self.active.get(job.id)
            log_path = get_storage().abs(job.log_path) if job.log_path else jobs_svc.log_file(job)
            if active is None:
                handle = await self.runner.find(job.id, job.container_id)
                if handle is None:
                    await self._system(job.id, log_path, "scheduler restarted and the job process is gone")
                    await jobs_svc.finish(session, job, "failed", error="scheduler restarted while the job was running")
                    continue
                active = ActiveJob(handle=handle, log_path=log_path)
                self.active[job.id] = active
                self._start_tail(job.id, active, from_end=True)
                await self._system(job.id, log_path, "scheduler restarted, re-attached to the running job")
            state = await self.runner.inspect(active.handle)
            if state.running:
                if job.cancel_requested_at and not active.stopping:
                    active.stopping = True
                    await self._system(job.id, log_path, "stop requested (SIGTERM, grace 10s)")
                    await self.runner.stop(active.handle, grace=10)
                elif utcnow() > jobs_svc.deadline(job) and not active.stopping:
                    active.stopping = True
                    active.timed_out = True
                    await self._system(job.id, log_path, f"timeout after {job.timeout_minutes} minutes, stopping")
                    await self.runner.stop(active.handle, grace=10)
                else:
                    await self._watch(session, job, active)
                continue
            # exited: re-read the row, the trainer's final status / error may have landed after our select
            await self._stop_tail(active)
            await session.refresh(job)
            trainer_status = (job.metrics or {}).get("_trainer_status")
            if job.cancel_requested_at:
                status, error = "cancelled", None
            elif active.timed_out:
                status, error = "failed", f"timeout after {job.timeout_minutes} minutes"
            elif active.stop_reason:
                status, error = "failed", active.stop_reason
            elif trainer_status == "succeeded" and state.exit_code in (0, None):
                status, error = "succeeded", None
            else:
                tail = jobs_svc.read_log(job, None, 20)[0]
                code = "unknown" if state.exit_code is None else state.exit_code
                error = job.error_message or f"exit code {code}; last log: " + " | ".join(tail[-5:])[:1500]
                status = "failed"
            peak = f", peak memory {active.peak_memory_mb} MB" if active.peak_memory_mb else ""
            await self._system(job.id, log_path, f"process exited ({state.exit_code}) → {status}{peak}")
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
        running_jobs = [j for jobs in (await node_svc.gpu_jobs_map(session)).values() for j in jobs]
        readings = node_svc.detect_gpus() if pool.gpu_indices else []
        measured: dict[int, int] = {}
        if readings and running_jobs:
            pids_by_job = {jid: set(self.runner.pids(a.handle)) for jid, a in self.active.items()}
            measured = gpu_svc.measured_by_job(pool.gpu_indices, pids_by_job)
        gpu_slots = gpu_svc.slots_from(
            pool.gpu_indices, running_jobs, readings, measured=measured, warmup_s=self.settings.gpu_warmup_s
        )
        used_cpus = await node_svc.cpu_core_map(session)
        free_cores = [c for c in pool_cores(pool.cpu_cores) if c not in used_cpus]
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
        hold_gpus_for_head = False  # a long-waiting multi-GPU head must not be starved by 1-GPU backfill forever
        for i, job in enumerate(queued):
            if slots <= 0:
                break
            if hold_gpus_for_head and job.requested_gpu > 0:
                continue
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
            gpus = gpu_svc.plan(
                job,
                gpu_slots,
                share=pool.gpu_share,
                busy_threshold=self.settings.gpu_busy_threshold,
                reserve_mb=self.settings.gpu_reserve_mb,
            )
            fits_pool = (
                (job.requested_gpu == 0 or len(gpus) == job.requested_gpu)
                and float(job.requested_cpu) <= free_cpu
                and job.requested_memory_mb <= free_mem
            )
            if not (fits_project and fits_pool) or p.id in launched_projects:
                if fits_project and job.requested_gpu > 0 and not gpus and p.id not in launched_projects:
                    await self._note_gpu_wait(job, gpu_slots)
                    if i == 0 and utcnow() - job.created_at > timedelta(seconds=BACKFILL_HOLD_S):
                        hold_gpus_for_head = True
                if not pool.allow_backfill:
                    break
                continue
            need_cores = max(1, int(-(-float(job.requested_cpu) // 1)))  # ceil
            cpus = free_cores[:need_cores] if len(free_cores) >= need_cores else []
            try:
                await self.launch(session, job, gpus, cpus)
            except jobs_svc.JobStateChanged as e:
                log.info("launch skipped", job_id=job.id, reason=str(e))
                continue
            except Exception as e:
                log.error("launch failed", job_id=job.id, error=repr(e))
                await self._system(job.id, jobs_svc.log_file(job), f"launch failed: {e!r}")
                await jobs_svc.finish(session, job, "failed", error=f"launch failed: {e!r}"[:1000])
                continue
            gpu_svc.place(job, gpus, gpu_slots)
            free_cores = [c for c in free_cores if c not in cpus]
            free_cpu -= float(job.requested_cpu)
            free_mem -= job.requested_memory_mb
            slots -= 1
            pu["running_jobs"] += 1
            pu["gpu"] += job.requested_gpu
            pu["cpu"] += float(job.requested_cpu)
            pu["memory_mb"] += job.requested_memory_mb
            launched_projects.add(p.id)

    async def _note_gpu_wait(self, job: Job, slots: dict[int, gpu_svc.GpuSlot]) -> None:
        now = asyncio.get_running_loop().time()
        if now - self._gpu_wait_logged.get(job.id, -1e9) < 60:
            return
        self._gpu_wait_logged[job.id] = now
        want = job.requested_gpu_memory_mb
        state = ", ".join(
            f"GPU {s.index}: "
            + (
                "exclusive job"
                if s.exclusive
                else f"{s.used_mb}/{s.total_mb} MB in use (ours {s.measured_mb} MB measured, "
                f"{s.pending_mb} MB still warming up) by {len(s.jobs)} job(s)"
                if s.total_mb
                else f"{len(s.jobs)} job(s)"
            )
            for s in slots.values()
        )
        need = f"{job.requested_gpu} GPU" + (f" with {want} MB free each" if want else " (exclusive)")
        await self._system(job.id, jobs_svc.log_file(job), f"waiting for {need}; {state or 'no GPU in the pool'}")

    async def launch(self, session: AsyncSession, job: Job, gpus: list[int], cpus: list[int]) -> None:
        s = self.settings
        storage = get_storage()
        project = job.project
        input_dir = storage.ensure(storage.job_input_dir(job.id))
        output_dir = storage.ensure(storage.job_dir(project.slug, job.id))
        storage.ensure(output_dir / "logs")
        log_path = output_dir / "logs" / "job.log"

        env: dict[str, str] = {
            "JOB_ID": str(job.id),
            "JOB_KIND": job.kind,
            "JOB_TOKEN": create_job_token(job.id, job.kind, job.timeout_minutes * 60 + 900, s),
            "BACKEND_URL": s.internal_backend_url,
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
        spec = LaunchSpec(
            job_id=job.id,
            kind=job.kind,
            env=env,
            input_dir=input_dir,
            output_dir=output_dir,
            model_dir=model_dir,
            zoo_dir=zoo_dir,
            log_path=log_path,
            gpus=gpus,
            cpus=cpus,
            cpu=float(job.requested_cpu),
            memory_mb=job.requested_memory_mb,
            gpu_memory_mb=job.requested_gpu_memory_mb,
            timeout_s=job.timeout_minutes * 60 + 60,
        )
        enf = self.runner.enforcement
        how_cpu = "cgroup" if enf.cpu else ("affinity" if (cpus and enf.cpuset) else "threads only")
        how_mem = "cgroup" if enf.memory else ("watchdog" if s.memory_watchdog else "not enforced")
        await jobs_svc.mark_scheduled(session, job, gpus, cpus)
        shared = f" ({spec.gpu_memory_mb} MB VRAM each, shared)" if spec.gpu_memory_mb and gpus else ""
        await self._system(
            job.id,
            log_path,
            f"scheduled: gpu={gpus or '[]'}{shared} "
            f"cpu={spec.cpu:g} ({how_cpu}{', cores ' + str(cpus) if cpus else ''}) "
            f"memory={spec.memory_mb}MB ({how_mem}) runner={self.runner.kind}",
        )
        handle = await self.runner.start(spec)
        await jobs_svc.mark_running(session, job, handle)
        await self._system(job.id, log_path, f"started {handle}, python={getattr(self.runner, 'python', '?')}")
        active = ActiveJob(handle=handle, log_path=log_path)
        self.active[job.id] = active
        self._start_tail(job.id, active, from_end=False)
        log.info("job launched", job_id=job.id, gpus=gpus, cpus=cpus, handle=handle)

    # --- cleanup -----------------------------------------------------------------------------

    async def cleanup(self, session: AsyncSession) -> None:
        purged = await uploads_svc.purge_expired(session)
        storage = get_storage()
        jobs_root = storage.abs("jobs")
        removed = 0
        if jobs_root.exists():
            stmt = select(Job.id).where(Job.status.in_(("succeeded", "failed", "cancelled")))
            terminal = set((await session.execute(stmt)).scalars().all())
            stmt = select(Job.id).where(Job.status.in_(("queued", "scheduled", "running")))
            live = set((await session.execute(stmt)).scalars().all())
            stale_before = (utcnow() - timedelta(days=2)).timestamp()
            for d in jobs_root.iterdir():
                if not (d.is_dir() and d.name.isdigit()):
                    continue
                job_id = int(d.name)
                # a queued job may wait for days (backlog, paused pool): its input must survive until it runs
                stale = d.stat().st_mtime < stale_before and job_id not in self.active and job_id not in live
                if job_id in terminal or stale:
                    storage.remove_tree(f"jobs/{d.name}")
                    removed += 1
        purged_samples = await usage_svc.purge(session, self.settings.usage_retention_days)
        purged_tools = tools_svc.purge_expired()
        ttl = (await settings_svc.get_tool_pool(session)).result_ttl_hours
        expired_results = await jobs_svc.expire_tool_outputs(session, ttl)
        if purged or removed or purged_samples or purged_tools or expired_results:
            log.info(
                "cleanup",
                purged_uploads=purged,
                removed_input_dirs=removed,
                purged_samples=purged_samples,
                purged_tool_uploads=purged_tools,
                expired_tool_results=expired_results,
            )
