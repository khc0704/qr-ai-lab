"""Data exploration reports: tabular profile (correlation, VIF, relevance, recommendations) and image quality drift."""

from __future__ import annotations

import numpy as np
import pandas as pd
from PIL import Image

from trainer.analysis import image as image_analysis
from trainer.analysis import tabular as tabular_analysis


def test_tabular_profile_finds_collinearity_and_relevance():
    rng = np.random.default_rng(0)
    n = 600
    x1 = rng.normal(size=n)
    x2 = x1 * 2 + rng.normal(scale=0.05, size=n)  # collinear with x1
    noise = rng.normal(size=n)  # irrelevant
    line = rng.choice(["A", "B", "C"], size=n)
    y = 3 * x1 + (line == "A") * 1.5 + rng.normal(scale=0.3, size=n)
    df = pd.DataFrame(
        {"lot_id": [f"L{i}" for i in range(n)], "x1": x1, "x2": x2, "noise": noise, "line": line, "yield": y}
    )
    df.loc[:50, "noise"] = np.nan
    rep = tabular_analysis.profile(df, target="yield", id_columns=["lot_id"], n_jobs=1)
    assert rep["rows"] == n and rep["relevance"]["task"] == "regression"
    pairs = rep["correlation"]["high_pairs"]
    assert pairs and {pairs[0]["a"], pairs[0]["b"]} == {"x1", "x2"} and abs(pairs[0]["r"]) > 0.95
    vif = {v["name"]: v["vif"] for v in rep["collinearity"]["vif"]}
    assert vif["x1"] is None or vif["x1"] > 10
    feats = {f["name"]: f for f in rep["relevance"]["features"]}
    assert feats["noise"]["score"] < feats["x1"]["score"] and rep["relevance"]["features"][0]["name"] in ("x1", "x2")
    assert feats["line"]["kind"] == "categorical" and feats["line"]["mutual_info"] > 0
    assert rep["relevance"]["model"]["holdout_score"] > 0.8
    texts = " ".join(r["text"] for r in rep["recommendations"])
    assert "共線" in texts and "解釋力" in texts
    compact = tabular_analysis.compact(rep)
    assert len(compact["relevance"]["features"]) <= 40


def test_tabular_profile_without_target_and_classification():
    df = pd.DataFrame(
        {"a": [1, 2, 3, 4, 5, 6, 7, 8] * 10, "b": [2, 4, 6, 8, 10, 12, 14, 16] * 10, "c": list("xyxyxyxy") * 10}
    )
    rep = tabular_analysis.profile(df)
    assert rep["relevance"]["target"] is None and any("目標欄位" in r["text"] for r in rep["recommendations"])
    rep = tabular_analysis.profile(df, target="c")
    assert rep["relevance"]["task"] == "classification" and rep["relevance"]["features"]


def test_image_quality_report_detects_brightness_drift(tmp_path):
    rng = np.random.default_rng(1)
    for group, base in (("tool_a", 90), ("tool_b", 150)):
        d = tmp_path / group
        d.mkdir()
        for i in range(8):
            a = np.clip(rng.normal(base, 20, size=(48, 64)), 0, 255).astype(np.uint8)
            Image.fromarray(a).save(d / f"img{i}.png")
    rep = image_analysis.quality_report(tmp_path, embedding="metrics")
    assert rep["images_total"] == 16 and [g["name"] for g in rep["groups"]] == ["tool_a", "tool_b"]
    assert rep["drift"][0]["metric"].startswith("brightness")
    assert rep["similarity"]["labels"] == ["tool_a", "tool_b"] and len(rep["points"]) == 16
    assert rep["silhouette"] is not None and any("飄" in r["text"] for r in rep["recommendations"])
    rep2 = image_analysis.quality_report(tmp_path, embedding="dino", ctx=None)
    assert rep2["embedding"] == "metrics"  # falls back without weights
