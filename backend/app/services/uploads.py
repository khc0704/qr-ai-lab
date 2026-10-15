"""One-time uploads: streamed to DATA_ROOT/uploads/{id}/, claimed by exactly one job, purged on expiry."""

from __future__ import annotations

import csv
import io
import json
import shutil
import zipfile
from datetime import timedelta
from pathlib import Path
from typing import Any

import aiofiles
from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import bad_request, conflict, not_found
from app.db.base import utcnow
from app.models import Job, Project, Upload, User
from app.services import settings as settings_svc
from app.storage.local import get_storage

EXT_FORMAT = {
    ".csv": "csv",
    ".parquet": "parquet",
    ".zip": "image_folder",
    ".npy": "npy",
    ".jsonl": "jsonl",
    ".json": "coco",
}
IMAGE_EXT = (".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff")


def detect_spec(path: Path, fmt: str) -> dict[str, Any]:
    spec: dict[str, Any] = {}
    try:
        if fmt in ("csv", "spectrum_csv"):
            with path.open("r", encoding="utf-8", errors="replace", newline="") as f:
                header = next(csv.reader(f), [])
                rows = sum(1 for _ in f)
            spec = {"columns": header[:200], "row_count": rows}
        elif fmt == "jsonl":
            keys: list[str] = []
            rows = 0
            with path.open("r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    if not line.strip():
                        continue
                    rows += 1
                    if not keys:
                        keys = list(json.loads(line).keys())
            spec = {"columns": keys, "row_count": rows}
        elif fmt in ("image_folder", "yolo", "coco") and path.suffix == ".zip":
            with zipfile.ZipFile(path) as z:
                names = z.namelist()
                images = [n for n in names if n.lower().endswith(IMAGE_EXT)]
                classes = sorted({n.split("/")[-2] for n in images if "/" in n.strip("/")})
                spec = {
                    "image_count": len(images),
                    "row_count": len(images),
                    "classes": classes[:200],
                    "has_data_yaml": any(n.endswith("data.yaml") for n in names),
                }
        elif fmt == "npy":
            import numpy as np

            arr = np.load(path, mmap_mode="r")
            spec = {
                "shape": list(arr.shape),
                "row_count": int(arr.shape[0]) if arr.ndim else 1,
                "dtype": str(arr.dtype),
            }
        elif fmt == "parquet":
            import pyarrow.parquet as pq  # type: ignore[import-not-found]

            meta = pq.read_metadata(path)
            spec = {"columns": [c for c in pq.read_schema(path).names][:200], "row_count": meta.num_rows}
    except Exception as e:
        spec = {"detect_error": f"{type(e).__name__}: {e}"[:200]}
    return spec


async def create_from_upload(
    session: AsyncSession, actor: User, project: Project, file: UploadFile, fmt: str | None
) -> Upload:
    defaults = await settings_svc.get_job_defaults(session)
    filename = file.filename or "upload.bin"
    ext = Path(filename).suffix.lower()
    fmt = fmt or EXT_FORMAT.get(ext)
    if not fmt:
        raise bad_request("UNKNOWN_FORMAT", f"無法判斷格式：{filename}")
    storage = get_storage()
    up = Upload(
        project_id=project.id,
        original_filename=filename[:255],
        path="",
        size_bytes=0,
        format=fmt,
        status="pending",
        expires_at=utcnow() + timedelta(minutes=defaults.upload_ttl_minutes),
        created_by_id=actor.id,
    )
    session.add(up)
    await session.flush()
    target_dir = storage.ensure(storage.upload_dir(up.id))
    target = target_dir / f"data{ext or ''}"
    limit = defaults.upload_max_mb * 1024 * 1024
    size = 0
    async with aiofiles.open(target, "wb") as out:
        while chunk := await file.read(1 << 20):
            size += len(chunk)
            if size > limit:
                await out.close()
                shutil.rmtree(target_dir, ignore_errors=True)
                await session.rollback()
                raise bad_request("UPLOAD_TOO_LARGE", f"超過上限 {defaults.upload_max_mb} MB")
            await out.write(chunk)
    up.path = storage.rel(target)
    up.size_bytes = size
    up.detected_spec = detect_spec(target, fmt)
    await session.commit()
    return up


async def get(session: AsyncSession, project: Project, upload_id: int) -> Upload:
    up = await session.get(Upload, upload_id)
    if up is None or up.project_id != project.id:
        raise not_found("UPLOAD_NOT_FOUND", "找不到上傳")
    return up


def claim(up: Upload, job: Job) -> Path:
    """Move the uploaded file into the job's input dir. Called inside the job-create transaction."""
    if up.status != "pending":
        raise conflict("UPLOAD_ALREADY_CLAIMED", "此上傳已被使用或已過期")
    if up.expires_at < utcnow():
        raise conflict("UPLOAD_EXPIRED", "上傳已過期，請重新上傳")
    storage = get_storage()
    src = storage.abs(up.path)
    dst_dir = storage.ensure(storage.job_input_dir(job.id))
    dst = dst_dir / src.name
    shutil.move(str(src), str(dst))
    shutil.rmtree(src.parent, ignore_errors=True)
    up.status = "claimed"
    up.claimed_by_job_id = job.id
    return dst


async def purge_expired(session: AsyncSession) -> int:
    rows = (
        (await session.execute(select(Upload).where(Upload.status == "pending", Upload.expires_at < utcnow())))
        .scalars()
        .all()
    )
    storage = get_storage()
    for up in rows:
        storage.remove_tree(f"uploads/{up.id}")
        up.status = "purged"
    await session.commit()
    return len(rows)


def read_head(path: Path, n: int = 5) -> list[str]:
    with path.open("r", encoding="utf-8", errors="replace") as f:
        return [next(f, "").rstrip("\n") for _ in range(n)]


def csv_preview(text: str) -> list[list[str]]:
    return list(csv.reader(io.StringIO(text)))
