"""Shared ``retrieve`` helpers: the k most similar / least similar reference items for a query, with the
direction (``order``) the user picked on the inference form (config.order = similar | dissimilar | both)."""

from __future__ import annotations

from typing import Any

import numpy as np

ORDERS = ("similar", "dissimilar", "both")


def parse_order(options: dict[str, Any], default: str = "both") -> str:
    order = str(options.get("order") or default)
    if order not in ORDERS:
        raise ValueError("order 必須是 similar / dissimilar / both")
    return order


def neighbour_rows(sims: np.ndarray, order: str, k: int, labels: np.ndarray | None, ids: np.ndarray) -> dict[str, Any]:
    """One query's neighbours from its similarity row: ``most_similar`` / ``least_similar`` (per ``order``),
    ``neighbors`` = the list the user asked for first, plus the extreme similarities."""
    finite = np.flatnonzero(np.isfinite(sims))
    asc = finite[np.argsort(sims[finite])]
    least = [int(j) for j in asc[:k]]
    most = [int(j) for j in asc[::-1][:k]]

    def pack(js):
        rows = []
        for j in js:
            row = {"id": str(ids[j]), "similarity": round(float(sims[j]), 5)}
            if labels is not None:
                row["label"] = str(labels[j])
            rows.append(row)
        return rows

    out: dict[str, Any] = {
        "max_similarity": float(sims[most[0]]) if most else None,
        "min_similarity": float(sims[least[0]]) if least else None,
    }
    if order in ("similar", "both"):
        out["most_similar"] = pack(most)
    if order in ("dissimilar", "both"):
        out["least_similar"] = pack(least)
    out["neighbors"] = out["least_similar"] if order == "dissimilar" else out["most_similar"]
    return out
