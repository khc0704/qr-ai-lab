"""GPU placement by free VRAM (several jobs per GPU) and the admin's force-reset.

Placement rules (``plan``):
* a job without ``requested_gpu_memory_mb`` wants whole GPUs: only GPUs no job is placed on, and whose driver-reported
  memory use is under ``gpu_busy_threshold`` (another user's process), qualify;
* a job with ``requested_gpu_memory_mb`` may share a GPU that is not held exclusively, when
  ``total - max(driver used, Σ reserved) - gpu_reserve_mb >= requested``; best fit (least free VRAM left) packs jobs;
* without pynvml readings (no NVIDIA driver, tests) sharing degrades to counting: a GPU hosts at most one exclusive job
  or any number of sharing jobs whose reservations fit the total reported by the pool entry (unknown → unlimited).
"""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
from dataclasses import dataclass, field

import psutil
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import bad_request, not_found
from app.core.logging import get_logger
from app.models import Job, User
from app.schemas.admin import GpuResetResult, NodeGpu
from app.services import audit
from app.services import jobs as jobs_svc
from app.services import node as node_svc

log = get_logger("gpu")


@dataclass
class GpuSlot:
    index: int
    total_mb: int | None  # None = unknown (no pynvml)
    used_mb: int = 0  # driver reading (all processes)
    exclusive: bool = False  # a whole-GPU job is placed here
    reserved_mb: int = 0  # Σ requested_gpu_memory_mb of sharing jobs placed here
    jobs: list[int] = field(default_factory=list)

    def free_mb(self, reserve_mb: int) -> int | None:
        if self.total_mb is None:
            return None
        return self.total_mb - max(self.used_mb, self.reserved_mb) - reserve_mb


def slots_from(pool_indices: list[int], running: list[Job], readings: list[NodeGpu]) -> dict[int, GpuSlot]:
    by_index = {g.index: g for g in readings}
    slots: dict[int, GpuSlot] = {}
    for i in pool_indices:
        r = by_index.get(i)
        slots[i] = GpuSlot(index=i, total_mb=r.memory_total_mb if r else None, used_mb=r.memory_used_mb if r else 0)
    for j in running:
        for g in j.assigned_gpus or []:
            s = slots.get(int(g))
            if s is None:
                continue
            s.jobs.append(j.id)
            if j.requested_gpu_memory_mb is None:
                s.exclusive = True
            else:
                s.reserved_mb += j.requested_gpu_memory_mb
    return slots


def plan(job: Job, slots: dict[int, GpuSlot], *, share: bool, busy_threshold: float, reserve_mb: int) -> list[int]:
    """GPU indices for ``job`` or [] when it does not fit right now. Does not mutate ``slots``."""
    n = job.requested_gpu
    if n <= 0:
        return []
    want = job.requested_gpu_memory_mb if share else None
    candidates: list[tuple[float, int]] = []  # (sort key, index)
    for s in slots.values():
        if s.exclusive:
            continue
        if want is None:
            if s.jobs:
                continue
            if s.total_mb and s.used_mb / s.total_mb > busy_threshold:
                continue
            candidates.append((s.used_mb, s.index))
        else:
            free = s.free_mb(reserve_mb)
            if free is None:
                candidates.append((len(s.jobs), s.index))  # unknown capacity: spread by job count
            elif free >= want:
                candidates.append((free, s.index))  # best fit: least free first
    if len(candidates) < n:
        return []
    candidates.sort()
    return [i for _, i in candidates[:n]]


def place(job: Job, gpus: list[int], slots: dict[int, GpuSlot]) -> None:
    for g in gpus:
        s = slots[g]
        s.jobs.append(job.id)
        if job.requested_gpu_memory_mb is None:
            s.exclusive = True
        else:
            s.reserved_mb += job.requested_gpu_memory_mb


# --- reset ---------------------------------------------------------------------------------------


def gpu_processes(index: int) -> list[tuple[int, int]]:
    """(pid, used_mb) of compute processes on the GPU as seen by the driver (needs pynvml)."""
    try:
        import pynvml  # type: ignore[import-not-found]

        pynvml.nvmlInit()
        try:
            h = pynvml.nvmlDeviceGetHandleByIndex(index)
            procs = list(pynvml.nvmlDeviceGetComputeRunningProcesses(h))
            with contextlib.suppress(Exception):
                procs += list(pynvml.nvmlDeviceGetGraphicsRunningProcesses(h))
            out = []
            for p in procs:
                used = getattr(p, "usedGpuMemory", None)
                out.append((int(p.pid), int(used / 2**20) if isinstance(used, int) and used > 0 else 0))
            return out
        finally:
            pynvml.nvmlShutdown()
    except Exception:
        return []


def _kill(pid: int) -> bool:
    try:
        p = psutil.Process(pid)
        for c in p.children(recursive=True):
            with contextlib.suppress(psutil.Error):
                c.send_signal(signal.SIGKILL)
        p.send_signal(signal.SIGKILL)
        return True
    except psutil.NoSuchProcess:
        return True
    except (psutil.AccessDenied, PermissionError):
        return False


async def reset(session: AsyncSession, admin: User, index: int, mode: str, reason: str) -> GpuResetResult:
    s = get_settings()
    readings = {g.index: g for g in node_svc.detect_gpus()}
    before = readings[index].memory_used_mb if index in readings else None
    pool = await node_svc.pool_indices(session)
    if index not in pool and index not in readings:
        raise not_found("GPU_NOT_PRESENT", f"沒有 GPU {index}")
    running, _ = await jobs_svc.queue(session)
    ours = [j for j in running if index in (j.assigned_gpus or [])]
    stopped: list[int] = []
    for j in ours:
        try:
            await jobs_svc.cancel(session, admin, j, f"GPU {index} reset: {reason}", forced=True)
            stopped.append(j.id)
        except Exception as e:  # already finishing
            log.warning("gpu reset: cancel failed", job_id=j.id, error=repr(e))
    killed: list[int] = []
    skipped: list[int] = []
    if mode in ("all", "device"):
        me = os.getpid()
        for pid, _mb in gpu_processes(index):
            if pid == me:
                continue
            (killed if _kill(pid) else skipped).append(pid)
    command: str | None = None
    command_ok: bool | None = None
    output: str | None = None
    if mode == "device":
        if not s.gpu_reset_command:
            raise bad_request(
                "GPU_RESET_COMMAND_UNSET", "GPU_RESET_COMMAND 未設定（例如 sudo -n nvidia-smi --gpu-reset -i {index}）"
            )
        command = s.gpu_reset_command.format(index=index)
        try:
            r = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=120)
            command_ok = r.returncode == 0
            output = (r.stdout + r.stderr).strip()[-2000:]
        except Exception as e:
            command_ok = False
            output = repr(e)
    after = None
    if readings:
        fresh = {g.index: g for g in node_svc.detect_gpus()}
        after = fresh[index].memory_used_mb if index in fresh else None
    result = GpuResetResult(
        index=index,
        mode=mode,
        stopped_jobs=stopped,
        killed_pids=killed,
        skipped_pids=skipped,
        command=command,
        command_ok=command_ok,
        command_output=output,
        memory_used_mb_before=before,
        memory_used_mb_after=after,
    )
    await audit.record(session, admin.id, "gpu.reset", "gpu", index, {"reason": reason, **result.model_dump()})
    await session.commit()
    log.warning("gpu reset", index=index, mode=mode, stopped=stopped, killed=killed, skipped=skipped, by=admin.username)
    return result
