"""Admin-adjustable global settings (resource pool, job defaults) with a short in-process cache."""

from __future__ import annotations

import time

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import SystemSetting
from app.schemas.settings import JobDefaults, ResourcePool, ToolDefaults
from app.services import audit

RESOURCE_POOL = "resource_pool"
JOB_DEFAULTS = "job_defaults"
TOOL_DEFAULTS = "tool_defaults"
_cache: dict[str, tuple[float, dict]] = {}
CACHE_TTL = 10.0


async def _get(session: AsyncSession, key: str) -> dict | None:
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < CACHE_TTL:
        return hit[1]
    row = await session.get(SystemSetting, key)
    if row is None:
        return None
    _cache[key] = (time.monotonic(), dict(row.value))
    return dict(row.value)


async def _set(session: AsyncSession, key: str, value: dict, actor_id: int | None) -> None:
    row = await session.get(SystemSetting, key)
    if row is None:
        session.add(SystemSetting(key=key, value=value, updated_by_id=actor_id))
    else:
        row.value = value
        row.updated_by_id = actor_id
    _cache.pop(key, None)
    await session.flush()


def invalidate() -> None:
    _cache.clear()


async def get_resource_pool(session: AsyncSession) -> ResourcePool:
    v = await _get(session, RESOURCE_POOL)
    if v is None:
        pool = default_pool()
        await _set(session, RESOURCE_POOL, pool.model_dump(), None)
        await session.commit()
        return pool
    return ResourcePool.model_validate(v)


async def set_resource_pool(session: AsyncSession, pool: ResourcePool, actor_id: int) -> ResourcePool:
    before = await _get(session, RESOURCE_POOL)
    await _set(session, RESOURCE_POOL, pool.model_dump(), actor_id)
    await audit.record(
        session,
        actor_id,
        "settings.resource_pool.update",
        "settings",
        None,
        {"before": before, "after": pool.model_dump()},
    )
    await session.commit()
    return pool


async def get_job_defaults(session: AsyncSession) -> JobDefaults:
    v = await _get(session, JOB_DEFAULTS)
    if v is None:
        s = get_settings()
        d = JobDefaults(
            timeout_minutes=s.default_job_timeout_minutes,
            upload_max_mb=s.upload_max_mb,
            upload_ttl_minutes=s.upload_ttl_minutes,
            log_max_mb=s.log_max_mb,
        )
        await _set(session, JOB_DEFAULTS, d.model_dump(), None)
        await session.commit()
        return d
    return JobDefaults.model_validate(v)


async def set_job_defaults(session: AsyncSession, d: JobDefaults, actor_id: int) -> JobDefaults:
    await _set(session, JOB_DEFAULTS, d.model_dump(), actor_id)
    await audit.record(session, actor_id, "settings.job_defaults.update", "settings", None, d.model_dump())
    await session.commit()
    return d


async def get_tool_defaults(session: AsyncSession) -> ToolDefaults:
    v = await _get(session, TOOL_DEFAULTS)
    if v is None:
        d = ToolDefaults()
        await _set(session, TOOL_DEFAULTS, d.model_dump(), None)
        await session.commit()
        return d
    return ToolDefaults.model_validate(v)


async def set_tool_defaults(session: AsyncSession, d: ToolDefaults, actor_id: int) -> ToolDefaults:
    await _set(session, TOOL_DEFAULTS, d.model_dump(), actor_id)
    await audit.record(session, actor_id, "settings.tool_defaults.update", "settings", None, d.model_dump())
    await session.commit()
    return d


def default_pool() -> ResourcePool:
    """Seed from the physical node so a fresh install can schedule immediately."""
    from app.services.node import detect_gpus, physical_cpu_cores, physical_memory_mb

    gpus = detect_gpus()
    return ResourcePool(
        gpu_indices=[g.index for g in gpus],
        cpu_cores=max(1, physical_cpu_cores() - 2),
        memory_mb=max(1024, int(physical_memory_mb() * 0.8)),
        max_running_jobs=max(1, len(gpus)) if gpus else 2,
        allow_backfill=True,
    )
