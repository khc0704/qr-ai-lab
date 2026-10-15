"""Model zoo: the pretrained weights the catalog needs, kept under MODEL_ZOO_ROOT.

The server has no internet access, so admins fill the zoo themselves: upload through the browser, import from a
folder mounted on the server (MODEL_ZOO_IMPORT_ROOT), or fetch from an intranet URL (MODEL_ZOO_ALLOWED_HOSTS).
Trainers only ever read from the zoo (HF_HUB_OFFLINE etc. are set by the runner). Every import is verified
against the catalog's sha256 when one is pinned and recorded in manifest.json.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
import tarfile
import urllib.request
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import aiofiles
from fastapi import UploadFile

from app.catalog import loader
from app.core.config import get_settings
from app.core.errors import bad_request, conflict, not_found
from app.core.logging import get_logger
from app.schemas.admin import ModelZooEntry, ZooTask

log = get_logger("model_zoo")
ARCHIVE_SUFFIXES = (".zip", ".tar", ".tar.gz", ".tgz")
TASKS: dict[str, ZooTask] = {}  # weight id → progress of the running / last background import
_BACKGROUND: set[asyncio.Task] = set()


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def root() -> Path:
    r = get_settings().zoo_root
    r.mkdir(parents=True, exist_ok=True)
    return r


def weights() -> list[dict[str, Any]]:
    """Catalog weights with every family that uses them."""
    out: dict[str, dict[str, Any]] = {}
    for fid, fam in loader.load_catalog()["families"].items():
        for w in fam.get("weights", []):
            entry = out.setdefault(w["id"], {**w, "family": fid, "families": []})
            entry["families"].append(fid)
    return list(out.values())


def weight(weight_id: str) -> dict[str, Any]:
    for w in weights():
        if w["id"] == weight_id:
            return w
    raise not_found("WEIGHT_NOT_FOUND", f"目錄裡沒有權重 {weight_id}")


def target_of(w: dict[str, Any]) -> Path:
    return root() / w["file"].rstrip("/")


def _manifest_path() -> Path:
    return root() / "manifest.json"


def read_manifest() -> dict[str, Any]:
    p = _manifest_path()
    if not p.exists():
        return {"weights": {}}
    try:
        m = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"weights": {}}
    if "weights" not in m:  # legacy flat layout
        m = {"weights": m}
    return m


def write_manifest(m: dict[str, Any]) -> None:
    m["generated_at"] = _now()
    tmp = _manifest_path().with_suffix(".json.tmp")
    tmp.write_text(json.dumps(m, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(_manifest_path())


def sha256_of(path: Path) -> str:
    """File: content hash. Directory (HF snapshot): hash of (relative path, content) in sorted order; this is the
    same algorithm as scripts/fetch_model_zoo.py so a manifest produced there verifies here."""
    h = hashlib.sha256()
    if path.is_dir():
        for f in sorted(p for p in path.rglob("*") if p.is_file()):
            h.update(f.relative_to(path).as_posix().encode())
            h.update(f.read_bytes())
    else:
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
    return h.hexdigest()


def _present(target: Path) -> bool:
    if not target.exists():
        return False
    return any(target.iterdir()) if target.is_dir() else target.stat().st_size > 0


def _size(target: Path) -> int:
    if target.is_dir():
        return sum(p.stat().st_size for p in target.rglob("*") if p.is_file())
    return target.stat().st_size


def entry(w: dict[str, Any], manifest: dict[str, Any], *, verify: bool = False) -> ModelZooEntry:
    target = target_of(w)
    present = _present(target)
    rec = manifest["weights"].get(w["id"], {})
    expected = w.get("sha256") or rec.get("sha256")
    actual = sha256_of(target) if (present and verify) else None
    task = TASKS.get(w["id"])
    if task and task.state == "running":
        status = "importing"
    elif not present:
        status = "error" if (task and task.state == "error") else "missing"
    elif actual and expected and actual != expected:
        status = "mismatch"
    else:
        status = "present"
    return ModelZooEntry(
        id=w["id"],
        family=w["family"],
        families=w.get("families", [w["family"]]),
        file=w["file"],
        license=w.get("license"),
        source=w.get("source"),
        kind=w.get("kind", "file"),
        present=present,
        status=status,
        size_bytes=_size(target) if present else None,
        sha256_expected=expected,
        sha256_actual=actual,
        imported_at=rec.get("imported_at") or rec.get("fetched_at"),
        imported_from=rec.get("imported_from") or rec.get("source"),
        task=task,
    )


def status(*, verify: bool = False) -> list[ModelZooEntry]:
    m = read_manifest()
    return [entry(w, m, verify=verify) for w in weights()]


def families_ready() -> dict[str, bool]:
    """family id → at least one of the weights it can use is in the zoo. A family lists alternatives (e.g.
    dinov2-small / dinov2-base, yolo11n / yolo11s …); one of them is enough to train. Families without
    pretrained weights are always ready."""
    cat = loader.load_catalog()["families"]
    out: dict[str, bool] = {}
    for fid, fam in cat.items():
        ws = fam.get("weights", [])
        out[fid] = not ws or any(_present(target_of(w)) for w in ws)
    return out


def family_ready(fid: str | None) -> bool:
    return True if not fid else families_ready().get(fid, True)


# --- bringing files in ---------------------------------------------------------------------------


def _staging(weight_id: str) -> Path:
    d = root() / ".staging" / weight_id
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    return d


def _safe_extract(archive: Path, dest: Path) -> None:
    name = archive.name.lower()
    if name.endswith(".zip"):
        with zipfile.ZipFile(archive) as z:
            for m in z.infolist():
                p = Path(m.filename)
                if p.is_absolute() or ".." in p.parts:
                    raise ValueError(f"unsafe path in archive: {m.filename}")
            z.extractall(dest)
    elif name.endswith((".tar", ".tar.gz", ".tgz")):
        with tarfile.open(archive) as t:
            t.extractall(dest, filter="data")
    else:
        raise ValueError(f"unsupported archive: {archive.name}")


def _snapshot_dir(extracted: Path) -> Path:
    """An HF snapshot zip usually wraps everything in one folder; unwrap it."""
    entries = [p for p in extracted.iterdir() if not p.name.startswith("__MACOSX")]
    if len(entries) == 1 and entries[0].is_dir() and not (extracted / "config.json").exists():
        return entries[0]
    return extracted


def _install(w: dict[str, Any], staged: Path, *, source: str) -> ModelZooEntry:
    """Move the staged file / folder into place, verify, record. Raises on checksum mismatch."""
    target = target_of(w)
    if w.get("kind", "file") == "hf_repo":
        if staged.is_file():
            out = staged.parent / "extracted"
            out.mkdir(exist_ok=True)
            _safe_extract(staged, out)
            staged = _snapshot_dir(out)
        if not (staged / "config.json").exists():
            raise ValueError("Hugging Face 權重資料夾裡應有 config.json（請上傳整個 snapshot 的 zip）")
    elif staged.is_dir():
        raise ValueError("這個權重是單一檔案，請提供檔案而不是資料夾")
    digest = sha256_of(staged)
    expected = w.get("sha256")
    if expected and digest != expected:
        raise ValueError(f"sha256 不符：目錄登記 {expected[:12]}…，收到 {digest[:12]}…")
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_dir():
        shutil.rmtree(target)
    elif target.exists():
        target.unlink()
    shutil.move(str(staged), str(target))
    m = read_manifest()
    m["weights"][w["id"]] = {
        "file": w["file"],
        "sha256": digest,
        "source": w.get("source"),
        "license": w.get("license"),
        "imported_at": _now(),
        "imported_from": source,
    }
    write_manifest(m)
    shutil.rmtree(root() / ".staging" / w["id"], ignore_errors=True)
    log.info("model zoo import", weight=w["id"], source=source, sha256=digest[:12])
    return entry(w, m)


async def upload(weight_id: str, file: UploadFile) -> ModelZooEntry:
    w = weight(weight_id)
    _check_not_running(weight_id)
    s = get_settings()
    staging = _staging(weight_id)
    name = Path(file.filename or "upload").name
    if w.get("kind", "file") == "hf_repo" and not name.lower().endswith(ARCHIVE_SUFFIXES):
        raise bad_request("ARCHIVE_REQUIRED", "Hugging Face 權重請上傳整個資料夾的 zip / tar.gz")
    staged = staging / name
    limit = s.model_zoo_max_mb * 1024 * 1024
    size = 0
    async with aiofiles.open(staged, "wb") as out:
        while chunk := await file.read(1 << 20):
            size += len(chunk)
            if size > limit:
                shutil.rmtree(staging, ignore_errors=True)
                raise bad_request("TOO_LARGE", f"超過上限 {s.model_zoo_max_mb} MB")
            await out.write(chunk)
    try:
        return await asyncio.to_thread(_install, w, staged, source=f"upload:{name}")
    except ValueError as e:
        shutil.rmtree(staging, ignore_errors=True)
        raise bad_request("WEIGHT_INVALID", str(e)) from e


def _check_not_running(weight_id: str) -> None:
    t = TASKS.get(weight_id)
    if t and t.state == "running":
        raise conflict("IMPORT_RUNNING", "這個權重正在匯入中")


def _allowed_host(url: str) -> None:
    s = get_settings()
    u = urlparse(url)
    if u.scheme not in ("http", "https"):
        raise ValueError("只接受 http(s) URL")
    if s.model_zoo_allowed_hosts and u.hostname not in s.model_zoo_allowed_hosts:
        raise ValueError(f"主機 {u.hostname} 不在 MODEL_ZOO_ALLOWED_HOSTS 白名單")


def _allowed_path(path: str) -> Path:
    s = get_settings()
    if s.model_zoo_import_root is None:
        raise ValueError("未設定 MODEL_ZOO_IMPORT_ROOT，不能從伺服器路徑匯入")
    base = s.model_zoo_import_root.resolve()
    p = (base / path).resolve() if not Path(path).is_absolute() else Path(path).resolve()
    if not p.is_relative_to(base):
        raise ValueError(f"路徑必須在 {base} 底下")
    if not p.exists():
        raise ValueError(f"找不到 {p}")
    return p


def _download(url: str, dest: Path, task: ZooTask, limit: int) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "qr-ai-lab-model-zoo"})
    with urllib.request.urlopen(req, timeout=60) as r, dest.open("wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        task.total_mb = round(total / 2**20, 1) if total else None
        done = 0
        while chunk := r.read(1 << 20):
            done += len(chunk)
            if done > limit:
                raise ValueError(f"超過上限 {limit // 2**20} MB")
            f.write(chunk)
            task.downloaded_mb = round(done / 2**20, 1)
            if total:
                task.progress = min(0.99, done / total)


def _run_import(w: dict[str, Any], source: str, url: str | None, path: str | None, task: ZooTask) -> None:
    s = get_settings()
    staging = _staging(w["id"])
    try:
        if source == "url":
            assert url
            _allowed_host(url)
            name = Path(urlparse(url).path).name or "download"
            staged = staging / name
            _download(url, staged, task, s.model_zoo_max_mb * 1024 * 1024)
            origin = f"url:{url}"
        else:
            assert path
            src = _allowed_path(path)
            staged = staging / src.name
            if src.is_dir():
                shutil.copytree(src, staged)
            else:
                shutil.copy2(src, staged)
            origin = f"path:{src}"
        task.message = "verifying"
        _install(w, staged, source=origin)
        task.state, task.progress, task.message = "done", 1.0, None
    except Exception as e:
        shutil.rmtree(staging, ignore_errors=True)
        task.state, task.message = "error", f"{type(e).__name__}: {e}"[:500]
        log.warning("model zoo import failed", weight=w["id"], source=source, error=repr(e))
    finally:
        task.finished_at = _now()


async def start_import(weight_id: str, *, source: str, url: str | None, path: str | None) -> ZooTask:
    w = weight(weight_id)
    _check_not_running(weight_id)
    if source == "url":
        if not url:
            raise bad_request("URL_REQUIRED", "請提供 URL")
        try:
            _allowed_host(url)
        except ValueError as e:
            raise bad_request("URL_NOT_ALLOWED", str(e)) from e
    else:
        if not path:
            raise bad_request("PATH_REQUIRED", "請提供伺服器上的路徑")
        try:
            _allowed_path(path)
        except ValueError as e:
            raise bad_request("PATH_NOT_ALLOWED", str(e)) from e
    task = ZooTask(weight_id=weight_id, source=f"{source}:{url or path}", state="running", started_at=_now())
    TASKS[weight_id] = task
    bg = asyncio.create_task(asyncio.to_thread(_run_import, w, source, url, path, task), name=f"zoo-{weight_id}")
    _BACKGROUND.add(bg)
    bg.add_done_callback(_BACKGROUND.discard)
    return task


def tasks() -> list[ZooTask]:
    return sorted(TASKS.values(), key=lambda t: t.started_at, reverse=True)


def delete(weight_id: str) -> None:
    w = weight(weight_id)
    _check_not_running(weight_id)
    target = target_of(w)
    if target.is_dir():
        shutil.rmtree(target)
    elif target.exists():
        target.unlink()
    m = read_manifest()
    m["weights"].pop(weight_id, None)
    write_manifest(m)
    TASKS.pop(weight_id, None)
