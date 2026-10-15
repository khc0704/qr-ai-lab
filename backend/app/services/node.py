"""Physical node readings (psutil, optional pynvml) and model-zoo status."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import psutil
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.catalog import loader
from app.core.config import get_settings
from app.models import Job
from app.schemas.admin import Allocated, ModelZooEntry, NodeGpu, NodeStatus


def physical_cpu_cores() -> int:
    return psutil.cpu_count(logical=True) or 1


def physical_memory_mb() -> int:
    return int(psutil.virtual_memory().total / (1024 * 1024))


def detect_gpus() -> list[NodeGpu]:
    try:
        import pynvml  # type: ignore[import-not-found]

        pynvml.nvmlInit()
        out = []
        for i in range(pynvml.nvmlDeviceGetCount()):
            h = pynvml.nvmlDeviceGetHandleByIndex(i)
            mem = pynvml.nvmlDeviceGetMemoryInfo(h)
            util = pynvml.nvmlDeviceGetUtilizationRates(h).gpu
            name = pynvml.nvmlDeviceGetName(h)
            if isinstance(name, bytes):
                name = name.decode()
            out.append(
                NodeGpu(
                    index=i,
                    name=name,
                    memory_total_mb=int(mem.total / 2**20),
                    memory_used_mb=int(mem.used / 2**20),
                    utilization=int(util),
                )
            )
        pynvml.nvmlShutdown()
        return out
    except Exception:
        return []


async def allocated(session: AsyncSession) -> Allocated:
    rows = (await session.execute(select(Job).where(Job.status.in_(("scheduled", "running"))))).scalars().all()
    return Allocated(
        gpu=sum(j.requested_gpu for j in rows),
        cpu=float(sum(float(j.requested_cpu) for j in rows)),
        memory_mb=sum(j.requested_memory_mb for j in rows),
        running_jobs=len(rows),
    )


async def gpu_job_map(session: AsyncSession) -> dict[int, int]:
    rows = (await session.execute(select(Job).where(Job.status.in_(("scheduled", "running"))))).scalars().all()
    out: dict[int, int] = {}
    for j in rows:
        for g in j.assigned_gpus or []:
            out[int(g)] = j.id
    return out


async def node_status(session: AsyncSession) -> NodeStatus:
    s = get_settings()
    gpus = detect_gpus()
    gmap = await gpu_job_map(session)
    for g in gpus:
        g.job_id = gmap.get(g.index)
    vm = psutil.virtual_memory()
    s.data_root.mkdir(parents=True, exist_ok=True)
    du = psutil.disk_usage(str(s.data_root))
    return NodeStatus(
        gpus=gpus,
        cpu_cores=physical_cpu_cores(),
        cpu_used_cores=round(psutil.cpu_percent(interval=None) / 100 * physical_cpu_cores(), 1),
        memory_mb=int(vm.total / 2**20),
        memory_used_mb=int(vm.used / 2**20),
        disk_total_gb=int(du.total / 2**30),
        disk_free_gb=int(du.free / 2**30),
        allocated=await allocated(session),
    )


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def model_zoo_status(verify: bool = False) -> list[ModelZooEntry]:
    """Which pretrained weights the catalog needs and whether they are present under MODEL_ZOO_ROOT."""
    root = get_settings().zoo_root
    manifest: dict[str, dict] = {}
    mpath = root / "manifest.json"
    if mpath.exists():
        try:
            manifest = json.loads(mpath.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            manifest = {}
    out: list[ModelZooEntry] = []
    for w in loader.required_weights():
        target = root / w["file"]
        present = target.exists() and (any(target.iterdir()) if target.is_dir() else target.stat().st_size > 0)
        size = None
        actual = None
        if present and target.is_file():
            size = target.stat().st_size
            if verify:
                actual = _sha256(target)
        entry_manifest = (manifest.get("weights") or manifest).get(w["id"], {})
        out.append(
            ModelZooEntry(
                id=w["id"],
                family=w["family"],
                file=w["file"],
                license=w.get("license"),
                source=w.get("source"),
                kind=w.get("kind", "file"),
                present=present,
                size_bytes=size,
                sha256_expected=w.get("sha256") or entry_manifest.get("sha256"),
                sha256_actual=actual,
            )
        )
    return out
