from __future__ import annotations

import contextlib
import os
import shutil
from pathlib import Path

from app.core.config import Settings, get_settings


class LocalStorage:
    """All paths are relative to DATA_ROOT and never derived from user-provided names (see ARCHITECTURE §10)."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.root = (settings or get_settings()).data_root.resolve()

    def abs(self, rel: str) -> Path:
        p = (self.root / rel).resolve()
        if self.root not in p.parents and p != self.root:
            raise ValueError(f"path escapes DATA_ROOT: {rel}")
        return p

    def rel(self, path: Path) -> str:
        return str(path.resolve().relative_to(self.root))

    def project_dir(self, slug: str) -> Path:
        return self.abs(f"projects/{slug}")

    def job_dir(self, slug: str, job_id: int) -> Path:
        return self.abs(f"projects/{slug}/jobs/{job_id}")

    def job_log_path(self, slug: str, job_id: int) -> Path:
        return self.job_dir(slug, job_id) / "logs" / "job.log"

    def job_input_dir(self, job_id: int) -> Path:
        return self.abs(f"jobs/{job_id}/input")

    def upload_dir(self, upload_id: int) -> Path:
        return self.abs(f"uploads/{upload_id}")

    def ensure(self, path: Path) -> Path:
        path.mkdir(parents=True, exist_ok=True)
        return path

    def usage_bytes(self, rel: str) -> int:
        base = self.abs(rel)
        if not base.exists():
            return 0
        total = 0
        for dirpath, _dirs, files in os.walk(base):
            for f in files:
                with contextlib.suppress(OSError):
                    total += (Path(dirpath) / f).stat().st_size
        return total

    def remove_tree(self, rel: str) -> None:
        p = self.abs(rel)
        if p.exists():
            shutil.rmtree(p, ignore_errors=True)

    def free_bytes(self) -> int:
        self.root.mkdir(parents=True, exist_ok=True)
        st = shutil.disk_usage(self.root)
        return st.free


_storage: LocalStorage | None = None


def get_storage() -> LocalStorage:
    global _storage
    if _storage is None:
        _storage = LocalStorage()
    return _storage


def reset_storage() -> None:
    global _storage
    _storage = None
