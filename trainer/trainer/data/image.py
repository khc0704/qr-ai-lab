"""Image inputs: a zip (classification folders / YOLO layout) or an already-extracted folder."""

from __future__ import annotations

import shutil
import zipfile
from pathlib import Path

from trainer.paths import safe_join

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}


def materialize(input_dir: Path, work_dir: Path) -> Path:
    """Zip inputs are extracted into the (writable) work dir; /job/input itself may be read-only."""
    zips = sorted(input_dir.glob("*.zip"))
    if zips:
        target = work_dir / zips[0].stem
        if not target.exists():
            target.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(zips[0]) as z:
                extract_zip(z, target)
        return target
    return input_dir


def extract_zip(z: zipfile.ZipFile, target: Path) -> None:
    """Extract every member through ``safe_join``: the whole archive is validated first, so a crafted entry
    (``../../x``, absolute path) fails before anything is written and the message names it."""
    members = z.infolist()
    dests: list[tuple[zipfile.ZipInfo, Path]] = []
    for member in members:
        try:
            dests.append((member, safe_join(target, member.filename)))
        except ValueError as e:
            raise ValueError(f"zip 內的項目不安全，已中止：{member.filename!r}（{e}）") from e
    for member, dest in dests:
        if member.is_dir():
            dest.mkdir(parents=True, exist_ok=True)
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        with z.open(member) as src, dest.open("wb") as dst:
            shutil.copyfileobj(src, dst, 1 << 20)


def class_folders(root: Path) -> dict[str, list[Path]]:
    """{class_name: [image paths]} from <root>/<split?>/<class>/*.jpg."""
    out: dict[str, list[Path]] = {}
    for p in root.rglob("*"):
        if p.suffix.lower() in IMAGE_EXT and p.parent != root:
            out.setdefault(p.parent.name, []).append(p)
    return dict(sorted(out.items()))


def find_data_yaml(root: Path) -> Path | None:
    for p in root.rglob("data.yaml"):
        return p
    return None


def all_images(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*") if p.suffix.lower() in IMAGE_EXT)
