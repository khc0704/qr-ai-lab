"""Shared fixtures: synthetic datasets and the catalog families dict (what the backend puts in the job spec)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

CATALOG = Path(__file__).resolve().parents[2] / "backend" / "app" / "catalog" / "model_catalog.yaml"


def catalog() -> dict:
    with CATALOG.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def families_for_spec(*fids: str) -> dict:
    cat = catalog()["families"]
    return {
        fid: {
            k: cat[fid].get(k)
            for k in ("label", "framework", "defaults", "search_space", "inference_modes", "resources")
        }
        for fid in fids
    }


def cls_frame(n: int = 400, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    x1, x2 = rng.normal(size=n), rng.normal(size=n)
    line = rng.choice(["A", "B"], size=n)
    score = 1.5 * x1 - x2 + (line == "A") * 0.5 + rng.normal(scale=0.3, size=n)
    return pd.DataFrame({"x1": x1, "x2": x2, "line": line, "label": np.where(score > 0, "pass", "fail")})


def reg_frame(n: int = 400, seed: int = 1) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    x1, x2 = rng.normal(size=n), rng.normal(size=n)
    return pd.DataFrame({"x1": x1, "x2": x2, "yield_pct": 90 + 2 * x1 - x2 + rng.normal(scale=0.2, size=n)})


def anomaly_frame(n: int = 500, seed: int = 2) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    X = rng.normal(size=(n, 4))
    labels = np.zeros(n, dtype=int)
    X[-25:] += rng.choice([-6, 6], size=(25, 4))
    labels[-25:] = 1
    df = pd.DataFrame(X, columns=[f"p{i}" for i in range(4)])
    df["is_anomaly"] = labels
    return df


@pytest.fixture
def ctx(tmp_path):
    from trainer.models.base import Context

    return Context(work_dir=tmp_path / "work", cpu=2, gpu=0)
