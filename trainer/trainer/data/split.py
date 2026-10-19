from __future__ import annotations

import numpy as np


def holdout(n: int, y, task: str | None, val_ratio: float = 0.2, seed: int = 42) -> tuple[np.ndarray, np.ndarray]:
    """Train / validation indices. Stratified for classification when every class has ≥ 2 samples."""
    rng = np.random.default_rng(seed)
    if n < 5:
        idx = np.arange(n)
        return idx, idx
    n_val = max(1, int(round(n * val_ratio)))
    if task == "classification" and y is not None:
        labels = np.asarray(y)
        classes, counts = np.unique(labels, return_counts=True)
        if counts.min() >= 2:
            val: list[int] = []
            for c in classes:
                members = np.flatnonzero(labels == c)
                rng.shuffle(members)
                k = max(1, int(round(len(members) * val_ratio)))
                val.extend(members[:k].tolist())
            val_idx = np.array(sorted(val))
            train_idx = np.setdiff1d(np.arange(n), val_idx)
            return train_idx, val_idx
    perm = rng.permutation(n)
    return np.sort(perm[n_val:]), np.sort(perm[:n_val])
