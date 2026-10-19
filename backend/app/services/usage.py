"""Usage history: the scheduler samples node / pool / per-project numbers; the admin dashboard reads buckets."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import psutil
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import utcnow
from app.models import Job, Project, ResourceSample
from app.schemas.admin import UsageHistory, UsagePoint, UsageProject
from app.services import node as node_svc
from app.services import settings as settings_svc

MAX_HISTORY_ROWS = 4000
RANGES: dict[str, tuple[timedelta, int]] = {  # range → (window, bucket seconds)
    "1h": (timedelta(hours=1), 60),
    "6h": (timedelta(hours=6), 300),
    "24h": (timedelta(hours=24), 900),
    "7d": (timedelta(days=7), 3600),
    "30d": (timedelta(days=30), 4 * 3600),
}


# psutil computes cpu_percent() as the delta since the previous call on the SAME Process object (a fresh object
# always answers 0.0), so the objects are kept between samples.
_procs: dict[int, psutil.Process] = {}
# System-wide cpu_percent() is a delta since the previous call: prime it at import so the first sample after a
# restart measures the interval since startup instead of reporting 0.
psutil.cpu_percent(interval=None)


def _process(pid: int) -> psutil.Process:
    p = _procs.get(pid)
    if p is None or not p.is_running():
        p = psutil.Process(pid)
        p.cpu_percent(interval=None)  # prime: the next call returns the usage since now
        _procs[pid] = p
    return p


def _prune_processes(live: set[int]) -> None:
    for pid in list(_procs):
        if pid not in live:
            _procs.pop(pid, None)


def _proc_usage(pids: list[int]) -> tuple[float, int]:
    """(cpu cores in use, PSS/RSS MB) summed over the job's process tree."""
    cpu = 0.0
    mem = 0
    for pid in pids:
        try:
            p = _process(pid)
            cpu += p.cpu_percent(interval=None) / 100.0
            try:
                mem += p.memory_full_info().pss
            except (psutil.AccessDenied, AttributeError):
                mem += p.memory_info().rss
        except psutil.Error:
            continue
    return round(cpu, 2), mem // (1024 * 1024)


async def sample(session: AsyncSession, job_pids: dict[int, list[int]] | None = None) -> ResourceSample:
    """Write one sample. ``job_pids`` (job id → pids) comes from the scheduler so actual CPU / memory per
    project can be measured; without it only the granted numbers are recorded."""
    pool = await settings_svc.get_resource_pool(session)
    gpus = node_svc.detect_gpus()
    pool_gpus = [g for g in gpus if g.index in pool.gpu_indices] or gpus
    vm = psutil.virtual_memory()
    node = {
        "cpu_pct": psutil.cpu_percent(interval=None),
        "cpu_cores": node_svc.physical_cpu_cores(),
        "mem_used_mb": int(vm.used / 2**20),
        "mem_total_mb": int(vm.total / 2**20),
        "gpus": [
            {
                "index": g.index,
                "util": g.utilization,
                "mem_used_mb": g.memory_used_mb,
                "mem_total_mb": g.memory_total_mb,
            }
            for g in pool_gpus
        ],
    }
    running = (await session.execute(select(Job).where(Job.status.in_(("scheduled", "running"))))).scalars().all()
    projects: dict[str, dict[str, float]] = {}
    vram: dict[int, int] = {}
    _prune_processes({pid for pids in (job_pids or {}).values() for pid in pids})
    if job_pids and gpus:
        from app.services.gpu import measured_by_job

        vram = measured_by_job([g.index for g in pool_gpus], {jid: set(p) for jid, p in job_pids.items()})
    for j in running:
        p = projects.setdefault(
            str(j.project_id),
            {
                "gpu": 0,
                "cpu": 0.0,
                "memory_mb": 0,
                "running_jobs": 0,
                "cpu_actual": 0.0,
                "mem_actual_mb": 0,
                "gpu_mem_actual_mb": 0,
            },
        )
        p["gpu"] += j.requested_gpu
        p["cpu"] += float(j.requested_cpu)
        p["memory_mb"] += j.requested_memory_mb
        p["running_jobs"] += 1
        p["gpu_mem_actual_mb"] += vram.get(j.id, 0)
        if job_pids and j.id in job_pids:
            c, m = _proc_usage(job_pids[j.id])
            p["cpu_actual"] += c
            p["mem_actual_mb"] += m
    payload: dict[str, Any] = {
        "node": node,
        "pool": {
            "gpu": sum(j.requested_gpu for j in running),
            "cpu": float(sum(float(j.requested_cpu) for j in running)),
            "memory_mb": sum(j.requested_memory_mb for j in running),
            "running_jobs": len(running),
            "gpu_total": len(pool.gpu_indices),
            "cpu_total": pool.cpu_cores,
            "memory_total_mb": pool.memory_mb,
        },
        "projects": projects,
    }
    row = ResourceSample(sampled_at=utcnow(), payload=payload)
    session.add(row)
    await session.commit()
    return row


async def purge(session: AsyncSession, retention_days: int) -> int:
    cutoff = utcnow() - timedelta(days=retention_days)
    r = await session.execute(delete(ResourceSample).where(ResourceSample.sampled_at < cutoff))
    await session.commit()
    return int(r.rowcount or 0)


def _bucket_start(t: datetime, bucket_s: int) -> datetime:
    epoch = int(t.timestamp())
    return datetime.utcfromtimestamp(epoch - epoch % bucket_s)


async def history(session: AsyncSession, range_: str, sample_interval_s: int) -> UsageHistory:
    if range_ not in RANGES:
        range_ = "24h"
    window, bucket_s = RANGES[range_]
    since = utcnow() - window
    # A 30-day window at a 30 s interval is ~86 k rows of JSON: keep every k-th sample so a request stays bounded
    # (each bucket still averages dozens of samples).
    ids = list(
        (
            await session.execute(
                select(ResourceSample.id).where(ResourceSample.sampled_at >= since).order_by(ResourceSample.sampled_at)
            )
        ).scalars()
    )
    stride = max(1, -(-len(ids) // MAX_HISTORY_ROWS))
    keep = ids[::stride]
    rows: list[ResourceSample] = []
    for i in range(0, len(keep), 500):
        chunk = keep[i : i + 500]
        rows.extend((await session.execute(select(ResourceSample).where(ResourceSample.id.in_(chunk)))).scalars().all())
    rows.sort(key=lambda r: r.sampled_at)
    # bucket → accumulators
    buckets: dict[datetime, dict[str, Any]] = {}
    for r in rows:
        b = buckets.setdefault(_bucket_start(r.sampled_at, bucket_s), {"n": 0, "sum": {}, "proj": {}})
        b["n"] += 1
        p = r.payload
        node = p.get("node") or {}
        pool = p.get("pool") or {}
        gpus = node.get("gpus") or []
        vals = {
            "cpu_pct": node.get("cpu_pct"),
            "mem_used_mb": node.get("mem_used_mb"),
            "gpu_util": (sum(g.get("util", 0) for g in gpus) / len(gpus)) if gpus else None,
            "gpu_mem_used_mb": sum(g.get("mem_used_mb", 0) for g in gpus) if gpus else None,
            "alloc_gpu": pool.get("gpu"),
            "alloc_cpu": pool.get("cpu"),
            "alloc_memory_mb": pool.get("memory_mb"),
            "running_jobs": pool.get("running_jobs"),
        }
        for k, v in vals.items():
            if v is not None:
                acc = b["sum"].setdefault(k, [0.0, 0])
                acc[0] += float(v)
                acc[1] += 1
        for pid, pv in (p.get("projects") or {}).items():
            acc = b["proj"].setdefault(pid, {})
            for k, v in pv.items():
                acc[k] = acc.get(k, 0.0) + float(v)
    points: list[UsagePoint] = []
    share_num: dict[str, dict[str, float]] = {}  # project → metric → Σ value × seconds
    for t in sorted(buckets):
        b = buckets[t]
        avg = {k: v[0] / v[1] for k, v in b["sum"].items()}
        proj = {pid: {k: v / b["n"] for k, v in pv.items()} for pid, pv in b["proj"].items()}
        for pid, pv in proj.items():
            acc = share_num.setdefault(pid, {})
            for k, v in pv.items():
                acc[k] = acc.get(k, 0.0) + v * bucket_s
        points.append(UsagePoint(t=t.isoformat() + "Z", projects=proj, **avg))
    window_s = max(1.0, window.total_seconds())
    pool_now = await settings_svc.get_resource_pool(session)
    gpus_now = node_svc.detect_gpus()
    totals = {
        "cpu_cores": float(node_svc.physical_cpu_cores()),
        "memory_mb": float(node_svc.physical_memory_mb()),
        "gpu_count": float(len(gpus_now)),
        "gpu_memory_mb": float(sum(g.memory_total_mb for g in gpus_now)),
        "pool_gpu": float(len(pool_now.gpu_indices)),
        "pool_cpu": float(pool_now.cpu_cores),
        "pool_memory_mb": float(pool_now.memory_mb),
    }
    ids = [int(pid) for pid in share_num]
    projects: list[UsageProject] = []
    if ids:
        for p in (await session.execute(select(Project).where(Project.id.in_(ids)))).scalars().all():
            projects.append(
                UsageProject(
                    id=p.id,
                    slug=p.slug,
                    name=p.name,
                    gpu_limit=p.gpu_limit,
                    cpu_limit=float(p.cpu_limit),
                    memory_limit_mb=p.memory_limit_mb,
                    status=p.status,
                )
            )
    by_id = {str(p.id): p for p in projects}
    project_share: dict[str, dict[str, float]] = {}
    for pid, acc in share_num.items():
        p = by_id.get(pid)
        out: dict[str, float] = {}
        # share of the project's own quota and of the whole pool / node, time-weighted over the window
        for metric, limit_key, pool_key, node_key in (
            ("gpu", "gpu_limit", "pool_gpu", "gpu_count"),
            ("cpu", "cpu_limit", "pool_cpu", "cpu_cores"),
            ("memory_mb", "memory_limit_mb", "pool_memory_mb", "memory_mb"),
        ):
            avg = acc.get(metric, 0.0) / window_s  # average allocation over the window
            out[f"{metric}_avg"] = round(avg, 3)
            limit = float(getattr(p, limit_key)) if p else 0.0
            out[f"{metric}_of_quota"] = round(avg / limit * 100, 1) if limit else 0.0
            out[f"{metric}_of_pool"] = round(avg / totals[pool_key] * 100, 1) if totals[pool_key] else 0.0
            out[f"{metric}_of_node"] = round(avg / totals[node_key] * 100, 1) if totals[node_key] else 0.0
        out["cpu_actual_avg"] = round(acc.get("cpu_actual", 0.0) / window_s, 3)
        out["mem_actual_avg_mb"] = round(acc.get("mem_actual_mb", 0.0) / window_s, 1)
        out["gpu_mem_actual_avg_mb"] = round(acc.get("gpu_mem_actual_mb", 0.0) / window_s, 1)
        out["job_seconds"] = round(acc.get("running_jobs", 0.0), 0)
        project_share[pid] = out
    return UsageHistory(
        range=range_,
        bucket_s=bucket_s,
        sample_interval_s=sample_interval_s,
        points=points,
        totals=totals,
        projects=projects,
        project_share=project_share,
    )
