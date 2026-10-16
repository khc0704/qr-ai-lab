"""Path safety for names that come from user-controlled containers (zip members, object-store keys, URLs).

Every file written under a target directory from such a name goes through ``safe_join``: it refuses absolute
paths, drive letters, ``..`` components, NUL bytes and empty names, and then checks that the resolved target is
still inside the resolved root. The error names the offending entry so a failed job / preview says why.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath, PureWindowsPath


def safe_relpath(name: str) -> PurePosixPath:
    """Normalise an untrusted relative name into a POSIX path that cannot climb out of its root."""
    if not isinstance(name, str) or not name or "\x00" in name:
        raise ValueError(f"不安全的檔案路徑（空白或含 NUL）：{name!r}")
    text = name.replace("\\", "/")
    if text.startswith("/") or PureWindowsPath(text).drive or PureWindowsPath(name).is_absolute():
        raise ValueError(f"不安全的檔案路徑（絕對路徑）：{name!r}")
    parts = [p for p in text.split("/") if p not in ("", ".")]
    if not parts:
        raise ValueError(f"不安全的檔案路徑（沒有檔名）：{name!r}")
    if any(p == ".." for p in parts):
        raise ValueError(f"不安全的檔案路徑（含 ..）：{name!r}")
    return PurePosixPath(*parts)


def safe_join(root: Path, name: str) -> Path:
    """``root / name`` for an untrusted ``name``; raises ValueError when it would leave ``root``."""
    rel = safe_relpath(name)
    target = Path(root) / rel
    base = Path(root).resolve()
    if not target.resolve().is_relative_to(base):
        raise ValueError(f"檔案路徑逃出目標資料夾：{name!r}")
    return target
