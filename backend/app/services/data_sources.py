from __future__ import annotations

import asyncio
from typing import Any

import httpx
from sqlalchemy import func, select
from sqlalchemy import update as sql_update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import conflict, not_found
from app.core.security import decrypt_json, encrypt_json
from app.db.base import utcnow
from app.models import DataSource, Job, Project, User
from app.schemas.data_source import DataSourceCreate, DataSourceUpdate
from app.services import audit


async def list_for_project(session: AsyncSession, project_id: int) -> list[DataSource]:
    return list(
        (
            await session.execute(
                select(DataSource).where(DataSource.project_id == project_id).order_by(DataSource.created_at.desc())
            )
        )
        .scalars()
        .all()
    )


async def get(session: AsyncSession, project: Project, ds_id: int) -> DataSource:
    ds = await session.get(DataSource, ds_id)
    if ds is None or ds.project_id != project.id:
        raise not_found("DATA_SOURCE_NOT_FOUND", "找不到資料來源")
    return ds


def _creds_from(body: DataSourceCreate | DataSourceUpdate) -> dict[str, Any] | None:
    creds: dict[str, Any] = {}
    if body.access_key or body.secret_key:
        creds.update({"access_key": body.access_key, "secret_key": body.secret_key, "region": body.region})
    if body.headers:
        creds["headers"] = body.headers
    return creds or None


async def create(session: AsyncSession, actor: User, project: Project, body: DataSourceCreate) -> DataSource:
    exists = (
        await session.execute(
            select(DataSource).where(DataSource.project_id == project.id, DataSource.name == body.name)
        )
    ).scalar_one_or_none()
    if exists:
        raise conflict("DATA_SOURCE_NAME_TAKEN", "同名資料來源已存在")
    creds = _creds_from(body)
    ds = DataSource(
        project_id=project.id,
        name=body.name,
        kind=body.kind,
        endpoint=body.endpoint,
        bucket=body.bucket,
        object_path=body.object_path,
        url=body.url,
        credentials_enc=encrypt_json(creds) if creds else None,
        format=body.format,
        default_spec=body.default_spec,
        created_by_id=actor.id,
    )
    session.add(ds)
    await session.commit()
    return await get(session, project, ds.id)


async def update(
    session: AsyncSession, actor: User, project: Project, ds: DataSource, body: DataSourceUpdate
) -> DataSource:
    for k in ("name", "endpoint", "bucket", "object_path", "url", "format", "default_spec"):
        v = getattr(body, k)
        if v is not None:
            setattr(ds, k, v)
    creds = _creds_from(body)
    if creds:
        ds.credentials_enc = encrypt_json(creds)
    await session.commit()
    return await get(session, project, ds.id)


async def delete(session: AsyncSession, actor: User, project: Project, ds: DataSource) -> None:
    active = (
        await session.execute(
            select(func.count())
            .select_from(Job)
            .where(Job.data_source_id == ds.id, Job.status.in_(("queued", "scheduled", "running")))
        )
    ).scalar_one()
    if active:
        raise conflict("DATA_SOURCE_IN_USE", "有未結束的任務正在使用")
    # finished jobs keep the source's name in input.data_source_name; the FK is RESTRICT so unlink them first
    await session.execute(sql_update(Job).where(Job.data_source_id == ds.id).values(data_source_id=None))
    await session.delete(ds)
    await audit.record(
        session, actor.id, "data_source.delete", "project", project.id, {"data_source_id": ds.id, "name": ds.name}
    )
    await session.commit()


def credentials(ds: DataSource) -> dict[str, Any]:
    return decrypt_json(ds.credentials_enc)


def _check_minio_sync(ds: DataSource, creds: dict[str, Any]) -> str:
    from urllib.parse import urlparse

    from minio import Minio

    u = urlparse(ds.endpoint or "")
    client = Minio(
        u.netloc,
        access_key=creds.get("access_key"),
        secret_key=creds.get("secret_key"),
        secure=(u.scheme == "https"),
        region=creds.get("region"),
    )
    prefix = (ds.object_path or "").lstrip("/")
    objs = list(client.list_objects(ds.bucket, prefix=prefix, recursive=True))  # type: ignore[arg-type]
    if not objs:
        raise FileNotFoundError("找不到任何物件")
    total = sum(o.size or 0 for o in objs[:5000])
    return f"{len(objs):,} 個物件，約 {total / 2**20:.1f} MB"


async def _check_url(ds: DataSource, creds: dict[str, Any]) -> str:
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        r = await client.head(ds.url or "", headers=creds.get("headers") or {})
        if r.status_code >= 400:
            r = await client.get(ds.url or "", headers={**(creds.get("headers") or {}), "Range": "bytes=0-1023"})
        r.raise_for_status()
        size = r.headers.get("content-length")
        return f"HTTP {r.status_code}" + (f"，{int(size) / 2**20:.1f} MB" if size and size.isdigit() else "")


async def check(session: AsyncSession, ds: DataSource) -> DataSource:
    creds = credentials(ds)
    try:
        msg = (
            await asyncio.to_thread(_check_minio_sync, ds, creds) if ds.kind == "minio" else await _check_url(ds, creds)
        )
        ds.last_check_ok = True
        ds.last_check_message = msg[:255]
    except Exception as e:
        ds.last_check_ok = False
        ds.last_check_message = f"{type(e).__name__}: {e}"[:255]
    ds.last_checked_at = utcnow()
    await session.commit()
    return ds
