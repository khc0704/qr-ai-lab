"""Dataset: one in-memory view of the job input, loaded per data_type.

TABULAR  → X: DataFrame, y: Series | None
TEXT     → X: Series[str], y: Series | None
SEQUENCE / SPECTRUM → X: ndarray (N, T, C), y: ndarray | None
IMAGE    → X: list[Path], y: list[str] | None, root: extracted folder, data_yaml for detection / segmentation
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from trainer.data.image import IMAGE_EXT, all_images, class_folders, find_data_yaml, materialize
from trainer.data.sequence import load_windows
from trainer.data.tabular import find_table, read_table, split_xy
from trainer.data.text import read_text_table, split_text
from trainer.log import info


@dataclass
class Dataset:
    data_type: str
    task: str | None
    spec: dict[str, Any] = field(default_factory=dict)
    X: Any = None
    y: Any = None
    ids: list[str] = field(default_factory=list)
    root: Path | None = None
    data_yaml: Path | None = None
    classes: list[str] | None = None
    preprocess: list[dict[str, Any]] | None = None  # fitted preprocessing steps (stored with the model)

    def __len__(self) -> int:
        if self.X is None:
            return 0
        return len(self.X)

    @property
    def has_labels(self) -> bool:
        return self.y is not None and len(self.y) == len(self)


def load(
    data_type: str,
    task: str | None,
    input_dir: Path,
    spec: dict[str, Any],
    work_dir: Path,
    *,
    inline_rows: list[dict[str, Any]] | None = None,
    preprocess_state: list[dict[str, Any]] | None = None,
) -> Dataset:
    """Load the job input. Preprocessing: `preprocess_state` (from the model) is replayed as-is; otherwise
    `spec.preprocess` steps are fitted on this data and the fitted state is kept in `ds.preprocess`."""
    spec = dict(spec or {})
    ds = Dataset(data_type=data_type, task=task, spec=spec)
    pre = _Pre(data_type, task, spec, preprocess_state, work_dir)
    if inline_rows is not None:
        _load_inline(ds, inline_rows, pre)
    elif data_type == "TABULAR":
        _from_frame(ds, pre.frame(read_table(find_table(input_dir))))
    elif data_type == "TEXT":
        df = pre.frame(read_text_table(input_dir))
        texts, labels = split_text(df, spec)
        ds.X, ds.y = texts, labels
        ds.ids = _ids(df, spec)
    elif data_type in ("SEQUENCE", "SPECTRUM"):
        X, y = load_windows(input_dir, spec, data_type)
        ds.X, ds.y = pre.array(X), y
        ds.ids = [str(i) for i in range(len(ds.X))]
    elif data_type == "IMAGE":
        _load_images(ds, input_dir, work_dir, pre)
    else:
        raise ValueError(f"unknown data_type {data_type}")
    ds.preprocess = pre.state()
    info(f"dataset: {data_type} n={len(ds)}" + (f" labels={'yes' if ds.has_labels else 'no'}"))
    return ds


class _Pre:
    """Builds the preprocessing pipeline once and applies it to whichever container the data type uses."""

    def __init__(self, data_type: str, task: str | None, spec: dict[str, Any], state, work_dir: Path) -> None:
        from qrlab_preprocess import Pipeline

        protected = [
            c for c in (spec.get("target"), spec.get("id_column"), spec.get("label_column"), spec.get("label")) if c
        ]
        text_column = spec.get("text_column", "text")
        self.work_dir = work_dir
        self.replay = state is not None
        if state:
            self.pipe = Pipeline.from_json(data_type, state, protected=protected, text_column=text_column)
        elif spec.get("preprocess"):
            self.pipe = Pipeline.from_spec(
                data_type, spec["preprocess"], task_type=task, protected=protected, text_column=text_column
            )
        else:
            self.pipe = None
        if self.pipe:
            info(f"preprocess ({'replay' if self.replay else 'fit'}): " + " → ".join(self.pipe.describe()))

    def _run(self, data):
        if self.pipe is None:
            return data
        return self.pipe.transform(data) if self.replay else self.pipe.fit_transform(data)

    def frame(self, df):
        n = len(df)
        out = self._run(df)
        if self.pipe and len(out) != n:
            info(f"preprocess: rows {n} → {len(out)}")
        return out

    def array(self, X):
        return self._run(X)

    def images(self, images):
        return self._run(images)

    def state(self):
        return self.pipe.to_json() if self.pipe else None


def _ids(df: pd.DataFrame, spec: dict[str, Any]) -> list[str]:
    col = spec.get("id_column")
    if col and col in df.columns:
        return [str(v) for v in df[col].tolist()]
    return [str(i) for i in df.index.tolist()]


def _from_frame(ds: Dataset, df: pd.DataFrame) -> None:
    ds.ids = _ids(df, ds.spec)
    id_col = ds.spec.get("id_column")
    if id_col and id_col in df.columns:
        df = df.drop(columns=[id_col])
    target = ds.spec.get("target")
    if target and target not in df.columns:
        # inference input without the target column
        ds.spec = {**ds.spec, "target": None}
    X, y = split_xy(df, ds.spec)
    ds.X, ds.y = X, y


def _load_inline(ds: Dataset, rows: list[dict[str, Any]], pre: _Pre) -> None:
    if ds.data_type in ("SEQUENCE", "SPECTRUM"):
        values = [r.get("values") or r.get("spectrum") or r.get("series") for r in rows]
        if any(v is None for v in values):
            raise ValueError("inline rows for sequence / spectrum need a 'values' list per row")
        X = np.asarray(values, dtype=np.float32)
        if X.ndim == 2:
            X = X[:, :, None]
        ds.X = pre.array(X)
        ds.ids = [str(r.get("id", i)) for i, r in enumerate(rows)]
        return
    df = pre.frame(pd.DataFrame(rows))
    if ds.data_type == "TEXT":
        texts, labels = split_text(df, ds.spec)
        ds.X, ds.y = texts, labels
        ds.ids = _ids(df, ds.spec)
        return
    _from_frame(ds, df)


def _load_images(ds: Dataset, input_dir: Path, work_dir: Path, pre: _Pre) -> None:
    root = materialize(input_dir, work_dir / "images")
    if pre.pipe:
        root = _preprocess_image_tree(root, work_dir / "pre", pre)
    ds.root = root
    ds.data_yaml = find_data_yaml(root)
    if ds.task in ("detection", "segmentation"):
        ds.X = all_images(root)
        ds.ids = [str(p.relative_to(root)) for p in ds.X]
        return
    folders = class_folders(root)
    split_names = {"train", "val", "valid", "test", "images", "_extracted"}
    folders = {k: v for k, v in folders.items() if k not in split_names}
    if ds.task == "anomaly_detection":
        normal = [k for k in folders if k.lower() in ("good", "normal", "ok", "pass")]
        if normal:
            ds.X = [p for k in normal for p in folders[k]]
            ds.y = ["normal"] * len(ds.X)
            others = [(p, k) for k, v in folders.items() if k not in normal for p in v]
            if others:
                ds.X = ds.X + [p for p, _ in others]
                ds.y = ds.y + [k for _, k in others]
        else:
            ds.X = all_images(root)
            ds.y = None
    elif folders and sum(len(v) for v in folders.values()) >= len(all_images(root)) * 0.8:
        ds.X = [p for v in folders.values() for p in v]
        ds.y = [k for k, v in folders.items() for _ in v]
        ds.classes = list(folders.keys())
    else:
        ds.X = all_images(root)
        ds.y = None
    ds.ids = [str(p.relative_to(root)) for p in ds.X]


def _preprocess_image_tree(root: Path, target: Path, pre: _Pre) -> Path:
    """Copy the dataset tree (labels, data.yaml …) and write every image through the pipeline. Fitted ops see
    the whole image set at once (e.g. alignment reference = first image)."""
    import shutil

    from PIL import Image

    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(root, target, ignore=shutil.ignore_patterns(*[f"*{e}" for e in IMAGE_EXT]))
    paths = all_images(root)
    images = []
    for p in paths:
        im = Image.open(p)
        im.load()
        images.append(im)
    out = pre.images(images)
    for p, im in zip(paths, out, strict=True):
        dst = target / p.relative_to(root)
        dst.parent.mkdir(parents=True, exist_ok=True)
        if im.mode not in ("L", "RGB"):
            im = im.convert("RGB")
        im.save(dst)
    yaml_path = find_data_yaml(target)
    if yaml_path is not None:
        text = yaml_path.read_text(encoding="utf-8")
        yaml_path.write_text(text.replace(str(root), str(target)), encoding="utf-8")
    info(f"preprocess: {len(paths)} images written to {target.name}/")
    return target
