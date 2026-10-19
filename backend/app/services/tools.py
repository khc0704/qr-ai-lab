"""Standalone data tools (no project needed): upload → preview on a sample (real time) → run the heavy part as a
job in the shared tool pool (queue, limits, log, cleanup like every other job).

Uploads live under DATA_ROOT/tools/<id>/ (data.<ext> + meta.json) with no database row until a job claims the
file (moved into the job's input dir, deleted when the job ends) or the upload expires.
"""

from __future__ import annotations

import asyncio
import json
import secrets
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import aiofiles
from fastapi import UploadFile
from qrlab_preprocess.preview import run_preview
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import bad_request, conflict, not_found
from app.core.executors import in_preview_pool
from app.core.logging import get_logger
from app.db.base import utcnow
from app.models import Job, Project, User
from app.schemas.settings import ToolPoolStatus
from app.schemas.tools import PreviewRead, ToolUploadRead
from app.services import jobs as jobs_svc
from app.services import projects as projects_svc
from app.services import settings as settings_svc
from app.services.uploads import EXT_FORMAT, detect_spec
from app.storage.local import get_storage

log = get_logger("tools")
ROOT = "tools"
FORMATS_BY_TYPE: dict[str, tuple[str, ...]] = {
    "TABULAR": ("csv", "parquet", "jsonl"),
    "TEXT": ("csv", "parquet", "jsonl"),
    "SEQUENCE": ("csv", "npy"),
    "SPECTRUM": ("csv", "npy"),
    "IMAGE": ("image_folder", "image"),
}
IMAGE_EXT = (".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp")
ANALYSES: dict[str, tuple[str, ...]] = {"tabular_profile": ("TABULAR",), "image_quality": ("IMAGE",)}


def _dir(upload_id: str) -> Path:
    if not upload_id.isalnum() or len(upload_id) > 40:
        raise not_found("TOOL_UPLOAD_NOT_FOUND", "找不到上傳")
    return get_storage().abs(f"{ROOT}/{upload_id}")


def _meta_path(upload_id: str) -> Path:
    return _dir(upload_id) / "meta.json"


def _read(upload_id: str, user: User) -> tuple[dict[str, Any], Path]:
    mp = _meta_path(upload_id)
    if not mp.exists():
        raise not_found("TOOL_UPLOAD_NOT_FOUND", "找不到上傳（可能已建立任務或過期而刪除）")
    meta = json.loads(mp.read_text(encoding="utf-8"))
    if meta.get("owner_id") != user.id and not user.is_admin:
        raise not_found("TOOL_UPLOAD_NOT_FOUND", "找不到上傳")
    if datetime.fromisoformat(meta["expires_at"]) < utcnow():
        remove(upload_id)
        raise not_found("TOOL_UPLOAD_EXPIRED", "上傳已過期並刪除，請重新上傳")
    return meta, mp.parent / meta["file"]


def _to_read(meta: dict[str, Any]) -> ToolUploadRead:
    return ToolUploadRead(
        id=meta["id"],
        data_type=meta["data_type"],
        original_filename=meta["original_filename"],
        size_bytes=meta["size_bytes"],
        format=meta["format"],
        detected_spec=meta.get("detected_spec"),
        expires_at=datetime.fromisoformat(meta["expires_at"]),
        created_at=datetime.fromisoformat(meta["created_at"]),
    )


def remove(upload_id: str) -> None:
    get_storage().remove_tree(f"{ROOT}/{upload_id}")


async def create(user: User, file: UploadFile, data_type: str, fmt: str | None) -> ToolUploadRead:
    s = get_settings()
    if data_type not in FORMATS_BY_TYPE:
        raise bad_request("BAD_DATA_TYPE", f"未知的資料類型 {data_type}")
    filename = file.filename or "upload.bin"
    ext = Path(filename).suffix.lower()
    if data_type == "IMAGE":
        fmt = "image_folder" if ext == ".zip" else ("image" if ext in IMAGE_EXT else None)
    else:
        fmt = fmt or EXT_FORMAT.get(ext)
    if not fmt or fmt not in FORMATS_BY_TYPE[data_type]:
        raise bad_request(
            "UNKNOWN_FORMAT", f"{data_type} 不接受 {ext or filename}（可用：{', '.join(FORMATS_BY_TYPE[data_type])}）"
        )
    upload_id = secrets.token_hex(12)
    storage = get_storage()
    folder = storage.ensure(storage.abs(f"{ROOT}/{upload_id}"))
    target = folder / f"data{ext}"
    limit = s.upload_max_mb * 1024 * 1024
    size = 0
    async with aiofiles.open(target, "wb") as out:
        while chunk := await file.read(1 << 20):
            size += len(chunk)
            if size > limit:
                await out.close()
                remove(upload_id)
                raise bad_request("UPLOAD_TOO_LARGE", f"超過上限 {s.upload_max_mb} MB")
            await out.write(chunk)
    now = utcnow()
    meta = {
        "id": upload_id,
        "owner_id": user.id,
        "data_type": data_type,
        "original_filename": filename[:255],
        "file": target.name,
        "size_bytes": size,
        "format": fmt,
        "detected_spec": (await asyncio.to_thread(detect_spec, target, fmt)) if fmt != "image" else {"image_count": 1},
        "created_at": now.isoformat(),
        "expires_at": (now + timedelta(minutes=s.upload_ttl_minutes)).isoformat(),
    }
    (folder / "meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    return _to_read(meta)


def get(upload_id: str, user: User) -> ToolUploadRead:
    meta, _ = _read(upload_id, user)
    return _to_read(meta)


async def preview(
    upload_id: str, user: User, steps: list[dict[str, Any]], *, sample: int, spec: dict[str, Any], task_type: str | None
) -> PreviewRead:
    """Real-time preview on a bounded sample (the full run is a job): before / after payloads, per-step warnings
    and, for TABULAR / TEXT, per-column statistics of the input sample and of the pipeline output."""
    meta, path = _read(upload_id, user)
    timeout = get_settings().preview_timeout_s
    try:
        result = await asyncio.wait_for(
            in_preview_pool(
                run_preview,
                meta["data_type"],
                path,
                meta["format"],
                steps,
                sample=sample,
                spec={**(meta.get("detected_spec") or {}), **spec},
                task_type=task_type,
            ),
            timeout=timeout,
        )
        return PreviewRead.model_validate(result)
    except TimeoutError as e:
        raise bad_request("PREVIEW_TIMEOUT", f"預覽超過 {timeout:g} 秒，請減少取樣數或步驟") from e
    except ValueError as e:
        raise bad_request("PREPROCESS_INVALID", str(e)) from e
    except Exception as e:
        raise bad_request("PREVIEW_FAILED", f"無法預覽：{type(e).__name__}: {e}"[:500]) from e


async def start_preprocess_job(
    session: AsyncSession,
    upload_id: str,
    user: User,
    *,
    steps: list[dict[str, Any]],
    spec: dict[str, Any],
    task_type: str | None,
    name: str | None,
) -> Job:
    """Whole-file preprocessing as a job in the tool pool; the upload folder is consumed."""
    import qrlab_preprocess

    meta, path = _read(upload_id, user)
    try:
        qrlab_preprocess.validate(meta["data_type"], task_type, steps)
    except ValueError as e:
        raise bad_request("PREPROCESS_INVALID", str(e)) from e
    project = await _pool_for(session, user)
    full_spec = {**(meta.get("detected_spec") or {}), **spec, "preprocess": steps}
    job = await jobs_svc.create_tool_job(
        session,
        user,
        project,
        kind="preprocess",
        name=name or f"前處理：{meta['original_filename']}",
        data_type=meta["data_type"],
        src_file=path,
        original_filename=meta["original_filename"],
        fmt=meta["format"],
        spec=full_spec,
        config={"steps": steps, "task_type": task_type, "data_type": meta["data_type"]},
    )
    remove(upload_id)
    log.info("tool preprocess job", job_id=job.id, data_type=meta["data_type"], steps=len(steps), user=user.username)
    return job


async def start_analysis_job(
    session: AsyncSession, upload_id: str, user: User, *, analysis: str, params: dict[str, Any], name: str | None
) -> Job:
    meta, path = _read(upload_id, user)
    allowed = ANALYSES.get(analysis)
    if not allowed:
        raise bad_request("BAD_ANALYSIS", f"未知的分析 {analysis}")
    if meta["data_type"] not in allowed:
        raise bad_request(
            "ANALYSIS_DATA_TYPE", f"{analysis} 只適用於 {', '.join(allowed)}，這個檔案是 {meta['data_type']}"
        )
    project = await _pool_for(session, user)
    config: dict[str, Any] = {"analysis": analysis, "data_type": meta["data_type"], **params}
    requested_gpu = 0
    if analysis == "image_quality" and params.get("embedding") == "dino":
        if project.gpu_limit > 0:
            requested_gpu = 1
        else:
            config["embedding"] = "metrics"
            config["note"] = "工具池沒有 GPU 配額，embedding 改用 IQA 指標向量"
    job = await jobs_svc.create_tool_job(
        session,
        user,
        project,
        kind="analysis",
        name=name or f"分析：{meta['original_filename']}",
        data_type=meta["data_type"],
        src_file=path,
        original_filename=meta["original_filename"],
        fmt=meta["format"],
        spec={
            **(meta.get("detected_spec") or {}),
            **{k: v for k, v in params.items() if isinstance(v, (str, int, float))},
        },
        config=config,
        requested_gpu=requested_gpu,
        requested_gpu_memory_mb=4096 if requested_gpu else None,
    )
    remove(upload_id)
    log.info("tool analysis job", job_id=job.id, analysis=analysis, user=user.username)
    return job


ACTIVE = ("queued", "scheduled", "running")


async def _pool_for(session: AsyncSession, user: User) -> Project:
    """The shared tool pool, after the per-user fairness check (ToolPool.max_jobs_per_user)."""
    project = await projects_svc.shared(session, user)
    pool = await settings_svc.get_tool_pool(session)
    mine = await active_count(session, project, user)
    if mine >= pool.max_jobs_per_user:
        raise conflict(
            "TOOL_JOB_LIMIT",
            f"你已有 {mine} 個工具任務在排隊或執行（每人最多 {pool.max_jobs_per_user} 個），請等它們結束",
        )
    return project


async def active_count(session: AsyncSession, project: Project, user: User) -> int:
    return (
        await session.execute(
            select(func.count())
            .select_from(Job)
            .where(Job.project_id == project.id, Job.created_by_id == user.id, Job.status.in_(ACTIVE))
        )
    ).scalar_one()


async def pool_status(session: AsyncSession, user: User) -> ToolPoolStatus:
    project = await projects_svc.shared(session, user)
    pool = await settings_svc.get_tool_pool(session)
    return ToolPoolStatus(
        **pool.model_dump(), my_active_jobs=await active_count(session, project, user), slug=project.slug
    )


async def my_jobs(session: AsyncSession, user: User, limit: int = 50) -> list[Job]:
    project = await projects_svc.shared(session, user)
    rows, _ = await jobs_svc.list_jobs(session, project_id=project.id, created_by_id=user.id, page=1, page_size=limit)
    return rows


def purge_expired() -> int:
    root = get_storage().abs(ROOT)
    if not root.exists():
        return 0
    removed = 0
    now = utcnow()
    for d in root.iterdir():
        if not d.is_dir():
            continue
        mp = d / "meta.json"
        try:
            expires = datetime.fromisoformat(json.loads(mp.read_text(encoding="utf-8"))["expires_at"])
            stale = expires < now
        except Exception:
            stale = datetime.fromtimestamp(d.stat().st_mtime) < now - timedelta(days=1)
        if stale:
            shutil.rmtree(d, ignore_errors=True)
            removed += 1
    return removed
