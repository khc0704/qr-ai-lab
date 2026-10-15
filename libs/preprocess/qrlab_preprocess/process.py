"""Run a pipeline over a whole dataset and write the processed files (the standalone "資料前處理" tool).

Unlike ``preview`` (bounded sample, JSON payloads) this reads everything, fits the ops on the full data and
writes files the user takes away: processed data in the same family of format, ``pipeline.json`` (ops +
fitted state, replayable with ``Pipeline.from_json``) and ``summary.json``.
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from PIL import Image

from qrlab_preprocess import Pipeline, jsonable
from qrlab_preprocess.preview import IMAGE_EXT, _read_sequences

IMAGE_FIT_SAMPLE = 64  # fitted image ops (alignment reference …) learn from the first N images


def run_full(
    data_type: str,
    path: Path,
    fmt: str,
    steps: list[dict[str, Any]],
    out_dir: Path,
    *,
    spec: dict[str, Any] | None = None,
    task_type: str | None = None,
) -> dict[str, Any]:
    spec = spec or {}
    out_dir.mkdir(parents=True, exist_ok=True)
    protected = [
        c for c in (spec.get("target"), spec.get("id_column"), spec.get("label_column"), spec.get("label")) if c
    ]
    text_column = spec.get("text_column", "text")
    pipe = Pipeline.from_spec(data_type, steps, task_type=task_type, protected=protected, text_column=text_column)
    summary: dict[str, Any] = {"data_type": data_type, "format": fmt, "steps": pipe.describe(), "files": []}
    if data_type in ("TABULAR", "TEXT"):
        df = _read_frame_all(path, fmt)
        summary["before"] = {"rows": int(len(df)), "columns": [str(c) for c in df.columns]}
        out = pipe.fit_transform(df)
        name = _write_frame(out, out_dir, fmt)
        summary["after"] = {"rows": int(len(out)), "columns": [str(c) for c in out.columns]}
        summary["files"].append(name)
    elif data_type in ("SEQUENCE", "SPECTRUM"):
        X, ids = _read_sequences(path, fmt, spec, data_type, max_rows=10_000_000)
        summary["before"] = {"shape": [int(v) for v in X.shape]}
        out = np.asarray(pipe.fit_transform(X), dtype=np.float32)
        np.save(out_dir / "processed.npy", out)
        summary["files"].append("processed.npy")
        if out.ndim == 3 and out.shape[2] == 1:
            frame = pd.DataFrame(out[:, :, 0], columns=[f"c{i}" for i in range(out.shape[1])])
            frame.insert(0, "id", ids)
            frame.to_csv(out_dir / "processed.csv", index=False)
            summary["files"].append("processed.csv")
        else:
            pd.DataFrame({"id": ids}).to_csv(out_dir / "ids.csv", index=False)
            summary["files"].append("ids.csv")
        summary["after"] = {"shape": [int(v) for v in out.shape]}
    elif data_type == "IMAGE":
        n = _process_images(pipe, path, out_dir / "images")
        summary["before"] = {"images": n}
        summary["after"] = {"images": n}
        summary["files"].append("images/")
    else:
        raise ValueError(f"未知的 data_type {data_type}")
    (out_dir / "pipeline.json").write_text(
        json.dumps({"data_type": data_type, "steps": pipe.to_json()}, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    summary["files"] += ["pipeline.json", "summary.json"]
    (out_dir / "summary.json").write_text(json.dumps(jsonable(summary), ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


# --- frames ------------------------------------------------------------------------------------------


def _read_frame_all(path: Path, fmt: str) -> pd.DataFrame:
    if fmt == "parquet" or path.suffix == ".parquet":
        return pd.read_parquet(path)
    if fmt == "jsonl" or path.suffix == ".jsonl":
        rows = []
        with path.open(encoding="utf-8", errors="replace") as f:
            rows = [json.loads(line) for line in f if line.strip()]
        return pd.DataFrame(rows)
    return pd.read_csv(path)


def _write_frame(df: pd.DataFrame, out_dir: Path, fmt: str) -> str:
    if fmt == "parquet":
        df.to_parquet(out_dir / "processed.parquet", index=False)
        return "processed.parquet"
    if fmt == "jsonl":
        with (out_dir / "processed.jsonl").open("w", encoding="utf-8") as f:
            for rec in json.loads(df.to_json(orient="records", force_ascii=False, date_format="iso")):
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return "processed.jsonl"
    df.to_csv(out_dir / "processed.csv", index=False)
    return "processed.csv"


# --- images ------------------------------------------------------------------------------------------


def _iter_images(path: Path):
    """Yield (relative name, PIL image) for a zip, a folder or a single file."""
    if path.suffix == ".zip":
        with zipfile.ZipFile(path) as z:
            for m in z.namelist():
                if m.lower().endswith(IMAGE_EXT) and not Path(m).name.startswith(".") and not m.endswith("/"):
                    with z.open(m) as fh:
                        im = Image.open(io.BytesIO(fh.read()))
                        im.load()
                    yield m, im
    elif path.is_dir():
        for p in sorted(q for q in path.rglob("*") if q.suffix.lower() in IMAGE_EXT):
            yield str(p.relative_to(path)), Image.open(p)
    else:
        im = Image.open(path)
        im.load()
        yield path.name, im


def _save_image(im: Image.Image, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    ext = target.suffix.lower()
    if im.mode not in ("L", "RGB", "RGBA", "I;16", "I", "F") or (ext in (".jpg", ".jpeg") and im.mode not in ("L", "RGB")):
        im = im.convert("RGB")
    if im.mode in ("I", "F") and ext in (".jpg", ".jpeg", ".bmp", ".webp"):
        target = target.with_suffix(".png")
    im.save(target)


def _process_images(pipe: Pipeline, path: Path, out_dir: Path) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    names: list[str] = []
    batch: list[Image.Image] = []
    fitted = False
    n = 0

    def flush() -> None:
        nonlocal fitted, n
        if not batch:
            return
        processed = pipe.transform(batch) if fitted else pipe.fit_transform(batch)
        fitted = True
        for name, im in zip(names, processed, strict=True):
            _save_image(im, out_dir / name)
            n += 1
        names.clear()
        batch.clear()

    for name, im in _iter_images(path):
        names.append(name)
        batch.append(im)
        if len(batch) >= IMAGE_FIT_SAMPLE:
            flush()
    flush()
    if n == 0:
        raise ValueError("找不到影像檔")
    return n
