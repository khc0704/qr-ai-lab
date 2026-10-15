"""Standalone preprocessing tool: upload → preview → process whole file → download a zip. Nothing persists.

Files live under DATA_ROOT/tools/<id>/ (data.<ext>, meta.json, out/, result.zip) with no database row; the folder is
removed after the download, on an explicit delete, or by the scheduler's cleanup once it expires.
"""

from __future__ import annotations

import asyncio
import json
import secrets
import shutil
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import aiofiles
from fastapi import UploadFile
from qrlab_preprocess.preview import run_preview
from qrlab_preprocess.process import run_full

from app.core.config import get_settings
from app.core.errors import bad_request, not_found
from app.core.logging import get_logger
from app.db.base import utcnow
from app.models import User
from app.schemas.tools import ToolProcessResult, ToolUploadRead
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


def _dir(upload_id: str) -> Path:
    if not upload_id.isalnum() or len(upload_id) > 40:
        raise not_found("TOOL_UPLOAD_NOT_FOUND", "找不到上傳")
    return get_storage().abs(f"{ROOT}/{upload_id}")


def _meta_path(upload_id: str) -> Path:
    return _dir(upload_id) / "meta.json"


def _read(upload_id: str, user: User) -> tuple[dict[str, Any], Path]:
    mp = _meta_path(upload_id)
    if not mp.exists():
        raise not_found("TOOL_UPLOAD_NOT_FOUND", "找不到上傳（可能已下載或過期而刪除）")
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
        "detected_spec": detect_spec(target, fmt if fmt != "image" else "csv")
        if fmt != "image"
        else {"image_count": 1},
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
) -> dict[str, Any]:
    meta, path = _read(upload_id, user)
    timeout = get_settings().preview_timeout_s
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(
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
    except TimeoutError as e:
        raise bad_request("PREVIEW_TIMEOUT", f"預覽超過 {timeout:g} 秒，請減少取樣數或步驟") from e
    except ValueError as e:
        raise bad_request("PREPROCESS_INVALID", str(e)) from e
    except Exception as e:
        raise bad_request("PREVIEW_FAILED", f"無法預覽：{type(e).__name__}: {e}"[:500]) from e


async def process(
    upload_id: str, user: User, steps: list[dict[str, Any]], *, spec: dict[str, Any], task_type: str | None
) -> ToolProcessResult:
    meta, path = _read(upload_id, user)
    s = get_settings()
    out_dir = path.parent / "out"
    shutil.rmtree(out_dir, ignore_errors=True)
    try:
        summary = await asyncio.wait_for(
            asyncio.to_thread(
                run_full,
                meta["data_type"],
                path,
                meta["format"],
                steps,
                out_dir,
                spec={**(meta.get("detected_spec") or {}), **spec},
                task_type=task_type,
            ),
            timeout=s.tool_process_timeout_s,
        )
    except TimeoutError as e:
        raise bad_request("PROCESS_TIMEOUT", f"處理超過 {s.tool_process_timeout_s:g} 秒；請縮小資料或減少步驟") from e
    except ValueError as e:
        raise bad_request("PREPROCESS_INVALID", str(e)) from e
    except Exception as e:
        raise bad_request("PROCESS_FAILED", f"處理失敗：{type(e).__name__}: {e}"[:500]) from e
    zip_path = path.parent / "result.zip"
    await asyncio.to_thread(_zip_dir, out_dir, zip_path)
    shutil.rmtree(out_dir, ignore_errors=True)
    meta["result"] = {"zip": zip_path.name, "summary": summary, "size_bytes": zip_path.stat().st_size}
    _meta_path(upload_id).write_text(json.dumps(meta, ensure_ascii=False, default=str), encoding="utf-8")
    log.info("tool processed", upload_id=upload_id, data_type=meta["data_type"], steps=len(steps), user=user.username)
    return ToolProcessResult(
        id=upload_id,
        summary=summary,
        zip_size_bytes=zip_path.stat().st_size,
        download_path=f"/tools/uploads/{upload_id}/download",
    )


def _zip_dir(src: Path, zip_path: Path) -> None:
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for p in sorted(src.rglob("*")):
            if p.is_file():
                z.write(p, p.relative_to(src).as_posix())


def result_file(upload_id: str, user: User) -> tuple[Path, str]:
    """(zip path, download filename). The caller removes the folder once the response is sent."""
    meta, _ = _read(upload_id, user)
    res = meta.get("result")
    if not res:
        raise not_found("TOOL_RESULT_NOT_FOUND", "尚未處理")
    zip_path = _dir(upload_id) / res["zip"]
    if not zip_path.exists():
        raise not_found("TOOL_RESULT_NOT_FOUND", "結果已下載並刪除")
    stem = Path(meta["original_filename"]).stem or "data"
    return zip_path, f"{stem}-preprocessed.zip"


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
