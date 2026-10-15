from __future__ import annotations

import contextlib

import numpy as np
from sklearn import metrics as skm


def classification(y_true, y_pred, proba=None) -> dict[str, float]:
    out = {
        "f1_macro": float(skm.f1_score(y_true, y_pred, average="macro")),
        "accuracy": float(skm.accuracy_score(y_true, y_pred)),
    }
    classes = np.unique(y_true)
    if proba is not None and len(classes) == 2:
        with contextlib.suppress(ValueError):
            out["auroc"] = float(skm.roc_auc_score(y_true, proba[:, 1] if proba.ndim == 2 else proba))
    return out


def regression(y_true, y_pred) -> dict[str, float]:
    return {
        "rmse": float(np.sqrt(skm.mean_squared_error(y_true, y_pred))),
        "mae": float(skm.mean_absolute_error(y_true, y_pred)),
        "r2": float(skm.r2_score(y_true, y_pred)),
    }


def anomaly(scores, y_true=None, threshold: float | None = None) -> dict[str, float]:
    scores = np.asarray(scores, dtype=float)
    out: dict[str, float] = {"score_mean": float(scores.mean()), "score_std": float(scores.std())}
    if threshold is None:
        threshold = float(scores.mean() + 3 * scores.std())
    out["threshold"] = threshold
    out["flagged_ratio"] = float((scores > threshold).mean())
    if y_true is not None and len(np.unique(y_true)) == 2:
        out["auroc"] = float(skm.roc_auc_score(y_true, scores))
        out["f1"] = float(skm.f1_score(y_true, (scores > threshold).astype(int)))
    return out


def primary(task: str, m: dict[str, float]) -> tuple[str, float]:
    key = {
        "classification": "f1_macro",
        "regression": "rmse",
        "anomaly_detection": "auroc",
        "detection": "map50_95",
        "segmentation": "mask_map50_95",
    }[task]
    if key not in m:
        key = next(iter(m))
    return key, float(m[key])
