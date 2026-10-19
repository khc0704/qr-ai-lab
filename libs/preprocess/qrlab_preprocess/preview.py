"""Before / after samples for the UI. Reads a bounded sample from the uploaded file, applies the pipeline, and
returns JSON-friendly payloads (rows + column stats, thumbnails, downsampled curves, texts)."""

from __future__ import annotations

import base64
import io
import json
import zipfile
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from PIL import Image

from qrlab_preprocess import Pipeline

IMAGE_EXT = (".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp")
MAX_IMAGES = 8
MAX_ROWS_FOR_STATS = 5000
MAX_CURVE_POINTS = 512
THUMB = 256
# zip previews run in the API process: bound what one archive can make it read / decode
MAX_ZIP_ENTRY_BYTES = 64 * 1024 * 1024  # uncompressed size of one image entry
MAX_ZIP_RATIO = 100  # uncompressed / compressed above this (for entries > 1 MB) is a zip bomb
MAX_ZIP_ENTRIES_SCANNED = 20_000  # directory entries looked at while picking the sample


def run_preview(
    data_type: str,
    path: Path,
    fmt: str,
    steps: list[dict[str, Any]],
    *,
    sample: int = 5,
    spec: dict[str, Any] | None = None,
    task_type: str | None = None,
) -> dict[str, Any]:
    spec = spec or {}
    sample = max(1, min(int(sample), 50))
    protected = [
        c for c in (spec.get("target"), spec.get("id_column"), spec.get("label_column"), spec.get("label")) if c
    ]
    text_column = spec.get("text_column", "text")
    pipe = Pipeline.from_spec(data_type, steps, task_type=task_type, protected=protected, text_column=text_column)
    if data_type in ("TABULAR", "TEXT"):
        df = _read_frame(path, fmt, MAX_ROWS_FOR_STATS)
        before = _frame_payload(df, sample, text_column if data_type == "TEXT" else None)
        after_df = pipe.fit_transform(df)
        after = _frame_payload(after_df, sample, text_column if data_type == "TEXT" else None)
        return _result(
            data_type,
            pipe,
            before,
            after,
            rows_in=len(df),
            rows_out=len(after_df),
            columns_in=column_stats(df),
            columns_out=column_stats(after_df),
        )
    if data_type in ("SEQUENCE", "SPECTRUM"):
        X, ids = _read_sequences(path, fmt, spec, data_type, max_rows=MAX_ROWS_FOR_STATS)
        before = _curves_payload(X, ids, sample)
        after = _curves_payload(pipe.fit_transform(X), ids, sample)
        return _result(data_type, pipe, before, after)
    if data_type == "IMAGE":
        images, ids = _read_images(path, min(sample, MAX_IMAGES))
        before = _images_payload(images, ids)
        after = _images_payload(pipe.fit_transform(images), ids)
        return _result(data_type, pipe, before, after)
    raise ValueError(f"未知的 data_type {data_type}")


def _result(
    data_type: str,
    pipe: Pipeline,
    before: dict[str, Any],
    after: dict[str, Any],
    *,
    rows_in: int | None = None,
    rows_out: int | None = None,
    columns_in: list[dict[str, Any]] | None = None,
    columns_out: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """The preview payload. ``steps`` / ``before`` / ``after`` are the original fields; ``step_details`` carries
    each step's warnings, and the frame-based types add row counts and per-column statistics for the input
    sample and for the output of the whole pipeline."""
    return {
        "data_type": data_type,
        "steps": pipe.describe(),
        "step_details": pipe.report(),
        "warnings": pipe.warnings(),
        "before": before,
        "after": after,
        "rows_in": rows_in,
        "rows_out": rows_out,
        "columns_in": columns_in,
        "columns_out": columns_out,
    }


# --- readers ---------------------------------------------------------------------------------------


def _read_frame(path: Path, fmt: str, max_rows: int) -> pd.DataFrame:
    if fmt == "parquet" or path.suffix == ".parquet":
        return pd.read_parquet(path).head(max_rows)
    if fmt == "jsonl" or path.suffix == ".jsonl":
        rows = []
        with path.open(encoding="utf-8", errors="replace") as f:
            for line in f:
                if line.strip():
                    rows.append(json.loads(line))
                if len(rows) >= max_rows:
                    break
        return pd.DataFrame(rows)
    return pd.read_csv(path, nrows=max_rows)


def _read_sequences(
    path: Path, fmt: str, spec: dict[str, Any], data_type: str, max_rows: int
) -> tuple[np.ndarray, list[str]]:
    if fmt == "npy" or path.suffix == ".npy":
        a = np.load(path, mmap_mode="r")
        a = np.asarray(a[:max_rows], dtype=np.float32)
        if a.ndim == 2:
            a = a[:, :, None]
        return a, [str(i) for i in range(len(a))]
    df = pd.read_csv(path, nrows=max_rows)
    for c in (spec.get("label"), spec.get("id_column")):
        if c and c in df.columns:
            df = df.drop(columns=[c])
    if data_type == "SPECTRUM" or spec.get("layout", "wide") == "wide":
        a = df.select_dtypes("number").to_numpy(dtype=np.float32)[:, :, None]
        return a, [str(i) for i in range(len(a))]
    sid = spec.get("series_id", "series_id")
    window = int(spec.get("window", 256))
    feats = [c for c in df.select_dtypes("number").columns if c not in (sid, spec.get("time", "t"))]
    groups = df.groupby(sid) if sid in df.columns else [(0, df)]
    wins, ids = [], []
    for key, g in groups:
        v = g[feats].to_numpy(dtype=np.float32)
        if len(v) >= window:
            wins.append(v[:window])
            ids.append(str(key))
        if len(wins) >= 50:
            break
    if not wins:
        raise ValueError(f"沒有長度 ≥ {window} 的序列（請檢查 window / series_id）")
    return np.stack(wins), ids


def check_zip_entry(info: zipfile.ZipInfo) -> None:
    """Refuse entries that would make the reader decode far more than the archive holds."""
    if info.file_size > MAX_ZIP_ENTRY_BYTES:
        raise ValueError(
            f"zip 內的 {info.filename} 解壓後 {info.file_size / 2**20:.0f} MB，"
            f"超過預覽上限 {MAX_ZIP_ENTRY_BYTES // 2**20} MB"
        )
    if info.file_size > 2**20 and info.file_size > MAX_ZIP_RATIO * max(1, info.compress_size):
        raise ValueError(f"zip 內的 {info.filename} 壓縮比超過 {MAX_ZIP_RATIO} 倍，疑似 zip bomb，已拒絕")


def read_zip_entry(z: zipfile.ZipFile, info: zipfile.ZipInfo) -> bytes:
    """Read one entry with a hard byte cap (the header can lie about ``file_size``)."""
    check_zip_entry(info)
    with z.open(info) as fh:
        data = fh.read(MAX_ZIP_ENTRY_BYTES + 1)
    if len(data) > MAX_ZIP_ENTRY_BYTES:
        raise ValueError(f"zip 內的 {info.filename} 超過預覽上限 {MAX_ZIP_ENTRY_BYTES // 2**20} MB")
    return data


def _read_images(path: Path, n: int) -> tuple[list[Image.Image], list[str]]:
    images, ids = [], []
    if path.suffix == ".zip":
        with zipfile.ZipFile(path) as z:
            infos = [
                i
                for i in z.infolist()[:MAX_ZIP_ENTRIES_SCANNED]
                if i.filename.lower().endswith(IMAGE_EXT)
                and not Path(i.filename).name.startswith(".")
                and not i.is_dir()
            ]
            # spread the sample across folders (classes)
            by_dir: dict[str, list[zipfile.ZipInfo]] = {}
            for i in infos:
                by_dir.setdefault(str(Path(i.filename).parent), []).append(i)
            picked: list[zipfile.ZipInfo] = []
            while len(picked) < n and any(by_dir.values()):
                for d in list(by_dir):
                    if by_dir[d] and len(picked) < n:
                        picked.append(by_dir[d].pop(0))
            for info in picked:
                im = Image.open(io.BytesIO(read_zip_entry(z, info)))
                im.load()
                images.append(im)
                ids.append(info.filename)
    elif path.is_dir():
        for p in sorted(q for q in path.rglob("*") if q.suffix.lower() in IMAGE_EXT)[:n]:
            images.append(Image.open(p))
            ids.append(str(p.relative_to(path)))
    else:
        im = Image.open(path)
        im.load()
        images, ids = [im], [path.name]
    if not images:
        raise ValueError("找不到影像檔")
    return images, ids


# --- payloads --------------------------------------------------------------------------------------

MAX_TOP_VALUES = 5


def column_kind(s: pd.Series) -> str:
    """The four kinds the UI distinguishes: number | text | bool | datetime."""
    if pd.api.types.is_bool_dtype(s):
        return "bool"
    if pd.api.types.is_datetime64_any_dtype(s):
        return "datetime"
    if pd.api.types.is_numeric_dtype(s):
        return "number"
    return "text"


def _finite(v: float) -> float | None:
    return float(v) if np.isfinite(v) else None


def column_stats(df: pd.DataFrame) -> list[dict[str, Any]]:
    """Per-column statistics for a spreadsheet-like header (pure pandas, JSON-safe). Every entry has the same
    keys; the ones that do not apply to the column's kind are None / empty."""
    n = len(df)
    out: list[dict[str, Any]] = []
    for c in df.columns:
        s = df[c]
        kind = column_kind(s)
        missing = int(s.isna().sum())
        entry: dict[str, Any] = {
            "name": str(c),
            "dtype": kind,
            "missing": missing,
            "missing_ratio": round(missing / n, 4) if n else 0.0,
            "unique": 0,
            "min": None,
            "max": None,
            "mean": None,
            "top": [],
        }
        if kind == "number":
            v = s.astype("float64")
            finite = v[np.isfinite(v)]
            entry["unique"] = int(finite.nunique())
            if len(finite):
                entry.update(min=_finite(finite.min()), max=_finite(finite.max()), mean=_finite(finite.mean()))
        elif kind == "datetime":
            present = s.dropna()
            entry["unique"] = int(present.nunique())
            if len(present):
                entry.update(min=present.min().isoformat(), max=present.max().isoformat())
        else:
            present = s.dropna().astype(str)  # object columns may hold unhashable values (lists from jsonl)
            entry["unique"] = int(present.nunique())
            counts = present.value_counts().head(MAX_TOP_VALUES)
            entry["top"] = [{"value": str(k), "count": int(v)} for k, v in counts.items()]
        out.append(entry)
    return out


def _frame_payload(df: pd.DataFrame, sample: int, text_column: str | None) -> dict[str, Any]:
    stats = []
    for c in df.columns:
        s = df[c]
        entry: dict[str, Any] = {"column": str(c), "dtype": str(s.dtype), "missing": int(s.isna().sum())}
        if pd.api.types.is_numeric_dtype(s) and s.notna().any():
            entry.update(
                {
                    "mean": float(s.mean()),
                    "std": float(s.std() or 0.0),
                    "min": float(s.min()),
                    "max": float(s.max()),
                }
            )
        else:
            entry["unique"] = int(s.nunique())
        stats.append(entry)
    head = df.head(sample)
    rows = json.loads(head.to_json(orient="records", force_ascii=False, date_format="iso"))
    return {"row_count": len(df), "columns": [str(c) for c in df.columns], "rows": rows, "stats": stats}


def _curves_payload(X: np.ndarray, ids: list[str], sample: int) -> dict[str, Any]:
    X = np.asarray(X, dtype=np.float32)
    if X.ndim == 2:
        X = X[:, :, None]
    N, T, C = X.shape
    step = max(1, T // MAX_CURVE_POINTS)
    curves = []
    for n in range(min(sample, N)):
        curves.append({"id": ids[n], "values": [X[n, ::step, c].round(5).tolist() for c in range(C)]})
    finite = X[np.isfinite(X)]
    stats = {
        "shape": [int(N), int(T), int(C)],
        "mean": float(finite.mean()) if finite.size else None,
        "std": float(finite.std()) if finite.size else None,
        "min": float(finite.min()) if finite.size else None,
        "max": float(finite.max()) if finite.size else None,
        "nan_ratio": float(1 - finite.size / X.size) if X.size else 0.0,
    }
    return {"curves": curves, "stats": stats, "points_step": step}


def _images_payload(images: list[Image.Image], ids: list[str]) -> dict[str, Any]:
    out = []
    for im, i in zip(images, ids, strict=True):
        thumb = im.copy()
        thumb.thumbnail((THUMB, THUMB))
        if thumb.mode not in ("L", "RGB"):
            thumb = thumb.convert("RGB")
        buf = io.BytesIO()
        thumb.save(buf, format="PNG")
        a = np.asarray(im.convert("L"), dtype=np.float32)
        out.append(
            {
                "id": i,
                "width": im.width,
                "height": im.height,
                "mode": im.mode,
                "mean": float(a.mean()),
                "std": float(a.std()),
                "png_base64": base64.b64encode(buf.getvalue()).decode("ascii"),
            }
        )
    return {"images": out}
