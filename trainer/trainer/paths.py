"""Safe joins for file names the job did not choose itself (object-store keys, URL / Content-Disposition
names, zip members). The rules live in the shared preprocessing package so the backend's tool path and the
trainer refuse the same things."""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath

from qrlab_preprocess.paths import safe_join as _safe_join
from qrlab_preprocess.paths import safe_relpath

__all__ = ["safe_filename", "safe_join", "safe_relpath"]


def safe_join(root: Path, name: str) -> Path:
    """``root / name`` for an untrusted relative ``name``; ValueError (naming the entry) when it would escape."""
    return _safe_join(root, name)


def safe_filename(name: str | None, default: str = "data") -> str:
    """A bare file name (no directories) from an untrusted string such as a URL path or Content-Disposition."""
    if not name:
        return default
    base = PurePosixPath(name.replace("\\", "/")).name.strip()
    base = re.sub(r"[\x00-\x1f]", "", base)
    if base in ("", ".", ".."):
        return default
    return base
