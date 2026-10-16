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


def test_image_groups_collapse_common_root_and_flag_small_groups(tmp_path):
    rng = np.random.default_rng(2)
    root = tmp_path / "images"  # a zip made from one folder: images/<tool>/*.png → groups are the tools
    for group, base, n in (("tool_a", 90, 6), ("tool_b", 150, 6), ("tool_c", 120, 2)):
        d = root / group
        d.mkdir(parents=True)
        for i in range(n):
            a = np.clip(rng.normal(base, 20, size=(48, 64)), 0, 255).astype(np.uint8)
            Image.fromarray(a).save(d / f"img{i}.png")
    assert image_analysis._groups(tmp_path, sorted(root.rglob("*.png")))[:1] == ["tool_a"]
    rep = image_analysis.quality_report(tmp_path, embedding="metrics")
    groups = {g["name"]: g for g in rep["groups"]}
    assert set(groups) == {"tool_a", "tool_b", "tool_c"} and groups["tool_c"]["insufficient"]
    assert not groups["tool_a"]["insufficient"]
    # drift is computed over the two sufficient groups; tool_c is noted, never produces a 1e9 ratio
    ratios = [d["drift_ratio"] for d in rep["drift"] if d["drift_ratio"] is not None]
    assert ratios and max(ratios) < 1e6 and rep["drift"][0]["metric"].startswith("brightness")
    assert all("tool_c" in (d["note"] or "") for d in rep["drift"] if d["drift_ratio"] is not None)
    assert any("樣本不足" in r["text"] and "tool_c" in r["text"] for r in rep["recommendations"])


def test_image_drift_marks_tiny_groups_and_constant_metrics_insufficient(tmp_path):
    for group in ("a", "b"):
        d = tmp_path / group
        d.mkdir()
        for i in range(2):  # 2 images per group: nothing can be said about drift
            Image.fromarray(np.full((32, 32), 100 + i, dtype=np.uint8)).save(d / f"{i}.png")
    rep = image_analysis.quality_report(tmp_path, embedding="metrics")
    assert all(d["drift_ratio"] is None and d["insufficient"] and "樣本不足" in d["note"] for d in rep["drift"])
    assert not any("最會飄" in r["text"] for r in rep["recommendations"])
    # enough images but identical ones: constant metrics → "no within-group variation", not a huge ratio
    for group in ("a", "b"):
        for i in range(2, 5):
            Image.fromarray(np.full((32, 32), 100 if group == "a" else 160, dtype=np.uint8)).save(
                tmp_path / group / f"{i}.png"
            )
    rep = image_analysis.quality_report(tmp_path, embedding="metrics")
    flat = [d for d in rep["drift"] if d["drift_ratio"] is None]
    assert flat and all("群內無變化" in d["note"] or "樣本不足" in d["note"] for d in flat)
    assert all(d["drift_ratio"] < 1e6 for d in rep["drift"] if d["drift_ratio"] is not None)


def test_tabular_permutation_importance_is_capped():
    rng = np.random.default_rng(3)
    n, p = 9000, 70
    X = rng.normal(size=(n, p))
    y = 2 * X[:, 0] - X[:, 1] + rng.normal(scale=0.5, size=n)
    df = pd.DataFrame(X, columns=[f"c{i}" for i in range(p)])
    df["y"] = y
    rep = tabular_analysis.profile(df, target="y", n_jobs=1)
    m = rep["relevance"]["model"]
    assert m["columns_used"] == 50 and m["permutation_rows"] == 2000 and m["test_rows"] == 2700
    feats = {f["name"]: f for f in rep["relevance"]["features"]}
    assert feats["c0"]["importance_share"] > 0.3 and not feats["c0"].get("permutation_skipped")
    assert sum(1 for f in feats.values() if f.get("permutation_skipped")) == 20
    assert rep["relevance"]["features"][0]["name"] in ("c0", "c1")
