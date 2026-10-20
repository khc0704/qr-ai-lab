"""Small image helpers for explanations: a patch-level map (what the model attended to / what deviates) rendered
as a transparent heat overlay that the result page can lay over the user's own copy of the image.

The overlay is saved at the image's own size, transparent outside the area the backbone actually looked at
(DINO processors resize the short side and centre-crop), so stretching it over the original image lines up.
"""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath
from typing import Any

import numpy as np

MAX_OVERLAY_SIDE = 768


def overlay_name(image_id: Any, seen: set[str]) -> str:
    """Overlay file name from the image's relative path (``a/x.jpg`` → ``a__x.png``) so images with the same
    base name in different folders do not overwrite each other; ``seen`` breaks any remaining tie."""
    p = PurePosixPath(str(image_id).replace("\\", "/"))
    rel = (p.with_suffix("") if p.name else p).as_posix().strip("/")
    flat = re.sub(r"[^\w.\-]+", "_", rel.replace("/", "__")).strip("._") or "image"
    name, k = f"{flat}.png", 1
    while name in seen:
        k += 1
        name = f"{flat}_{k}.png"
    seen.add(name)
    return name


def patch_grid(values: np.ndarray) -> np.ndarray:
    """(L,) patch values → (g, g) grid (ViT patches are a square grid)."""
    v = np.asarray(values, dtype=np.float32).ravel()
    g = round(np.sqrt(len(v)))
    if g * g != len(v):
        g = max(1, int(np.sqrt(len(v))))
        v = v[: g * g]
    return v.reshape(g, g)


def normalize01(grid: np.ndarray) -> np.ndarray:
    lo, hi = float(np.nanmin(grid)), float(np.nanmax(grid))
    if not np.isfinite(lo) or not np.isfinite(hi) or hi - lo < 1e-9:
        return np.zeros_like(grid, dtype=np.float32)
    return ((grid - lo) / (hi - lo)).astype(np.float32)


def heat_rgba(norm: np.ndarray, alpha_max: float = 0.7) -> np.ndarray:
    """0‥1 grid → RGBA uint8 (blue → cyan → yellow → red, alpha grows with the value)."""
    v = np.clip(norm, 0, 1)
    r = np.clip(1.5 * v - 0.25, 0, 1)
    g = np.clip(1.0 - np.abs(v - 0.5) * 2.0 + 0.3, 0, 1)
    b = np.clip(1.0 - 1.5 * v, 0, 1)
    a = np.clip(0.15 + v * alpha_max, 0, 1)
    return (np.stack([r, g, b, a], axis=-1) * 255).astype(np.uint8)


def crop_box(width: int, height: int, processor) -> tuple[int, int, int, int]:
    """Region of the original image the DINO processor keeps: resize the short side to ``size.shortest_edge``
    then centre-crop ``crop_size`` → a centred square of ``min(w, h) * crop / shortest_edge`` pixels. Without a
    centre crop the whole image is used."""
    try:
        size = getattr(processor, "size", None) or {}
        crop = getattr(processor, "crop_size", None) or {}
        do_crop = bool(getattr(processor, "do_center_crop", False))
        short = float(size.get("shortest_edge") or 0)
        ch, cw = float(crop.get("height") or 0), float(crop.get("width") or 0)
    except Exception:
        do_crop, short, ch, cw = False, 0.0, 0.0, 0.0
    if not do_crop or short <= 0 or ch <= 0 or cw <= 0:
        return 0, 0, width, height
    scale = short / max(1, min(width, height))
    side_w, side_h = min(width, cw / scale), min(height, ch / scale)
    x0 = (width - side_w) / 2
    y0 = (height - side_h) / 2
    return round(x0), round(y0), round(x0 + side_w), round(y0 + side_h)


def save_overlay(
    out_dir: Path,
    name: str,
    grid: np.ndarray,
    image_size: tuple[int, int],
    box: tuple[int, int, int, int] | None = None,
) -> str:
    """Write ``out_dir/name`` (RGBA PNG at the image's size, bounded by MAX_OVERLAY_SIDE) and return ``name``."""
    from PIL import Image

    out_dir.mkdir(parents=True, exist_ok=True)
    w, h = image_size
    scale = min(1.0, MAX_OVERLAY_SIDE / max(1, max(w, h)))
    W, H = max(1, round(w * scale)), max(1, round(h * scale))
    x0, y0, x1, y1 = box or (0, 0, w, h)
    x0, y0, x1, y1 = (round(v * scale) for v in (x0, y0, x1, y1))
    heat = Image.fromarray(heat_rgba(normalize01(grid)), mode="RGBA").resize(
        (max(1, x1 - x0), max(1, y1 - y0)), Image.BILINEAR
    )
    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    canvas.paste(heat, (x0, y0))
    canvas.save(out_dir / name)
    return name
