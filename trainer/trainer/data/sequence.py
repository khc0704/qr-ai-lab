"""Sequences / spectra → windows array (N, T, C). Supports npy (N,T,C) or (N,T), csv long/wide tables."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


def load_windows(input_dir: Path, spec: dict, data_type: str) -> tuple[np.ndarray, np.ndarray | None]:
    files = sorted(list(input_dir.glob("**/*.npy")) + list(input_dir.glob("**/*.csv")))
    if not files:
        raise FileNotFoundError(f"no npy/csv under {input_dir}")
    labels: np.ndarray | None = None
    arrays = []
    for f in files:
        if f.suffix == ".npy":
            a = np.load(f)
            if a.ndim == 2:
                a = a[:, :, None]
            arrays.append(a.astype(np.float32))
        else:
            df = pd.read_csv(f)
            label_col = spec.get("label")
            if label_col and label_col in df.columns:
                labels = df[label_col].to_numpy()
                df = df.drop(columns=[label_col])
            if data_type == "SPECTRUM" or spec.get("layout", "wide") == "wide":
                # wide: one row per sample, columns = wavelengths / time steps
                num = df.select_dtypes("number").to_numpy(dtype=np.float32)
                arrays.append(num[:, :, None])
            else:
                # long: series_id, t, features...
                sid = spec.get("series_id", "series_id")
                window, stride = int(spec.get("window", 256)), int(spec.get("stride", 128))
                feats = [c for c in df.select_dtypes("number").columns if c not in (sid, spec.get("time", "t"))]
                groups = df.groupby(sid) if sid in df.columns else [(0, df)]
                wins = []
                for _, g in groups:
                    v = g[feats].to_numpy(dtype=np.float32)
                    for s in range(0, max(1, len(v) - window + 1), stride):
                        if len(v[s : s + window]) == window:
                            wins.append(v[s : s + window])
                arrays.append(np.stack(wins) if wins else np.zeros((0, window, len(feats)), np.float32))
    X = np.concatenate(arrays, axis=0)
    return X, labels
