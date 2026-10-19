"""Data exploration reports: tabular profile (correlation, VIF, relevance, recommendations) and image quality drift."""

from __future__ import annotations

import json

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


def test_image_quality_report_on_identical_images_is_json_safe(tmp_path):
    # identical images in every group: MAD = 0 for the outlier score, within-group IQR = 0, every Kruskal sample
    # tied (h / ties = 0 / 0), cosine silhouette on zero vectors — none of it may surface as NaN, because the
    # backend serialises the registered report with allow_nan=False and a NaN would fail the job
    for group, level in (("tool_a", 100), ("tool_b", 160)):
        d = tmp_path / group
        d.mkdir()
        for i in range(4):
            Image.fromarray(np.full((32, 32), level, dtype=np.uint8)).save(d / f"{i}.png")
    rep = image_analysis.quality_report(tmp_path, embedding="metrics")
    json.dumps(rep, allow_nan=False)
    assert rep["images_total"] == 8 and all(p["outlier"] == 0 for p in rep["points"]) and rep["outliers"] == []
    assert all(d["p_value"] is None or 0 <= d["p_value"] <= 1 for d in rep["drift"])
    assert all(d["drift_ratio"] is None or d["drift_ratio"] < 1e6 for d in rep["drift"])
    assert rep["silhouette"] is None or -1 <= rep["silhouette"] <= 1
    assert all(v is None or abs(v) <= 1 for row in rep["similarity"]["matrix"] for v in row)


def test_image_quality_report_tolerates_metrics_that_cannot_be_computed(tmp_path, monkeypatch):
    rng = np.random.default_rng(4)
    for group, base in (("tool_a", 90), ("tool_b", 150)):
        d = tmp_path / group
        d.mkdir()
        for i in range(4):
            a = np.clip(rng.normal(base, 20, size=(48, 64)), 0, 255).astype(np.uint8)
            Image.fromarray(a).save(d / f"img{i}.png")
    real = image_analysis.image_metrics

    def broken(im):  # one metric is NaN on every image, another is inf on some
        m = real(im)
        m["spectral_slope"] = float("nan")
        m["snr"] = float("inf") if im.size[0] % 2 == 0 else m["snr"]
        return m

    monkeypatch.setattr(image_analysis, "image_metrics", broken)
    rep = image_analysis.quality_report(tmp_path, embedding="metrics")
    json.dumps(rep, allow_nan=False)
    slope = next(d for d in rep["drift"] if d["metric"] == "spectral_slope")
    assert slope["drift_ratio"] is None and slope["insufficient"] and "無法計算" in slope["note"]
    assert slope["group_medians"] == {"tool_a": None, "tool_b": None} and slope["p_value"] is None
    assert all(g["median"]["spectral_slope"] is None and g["iqr"]["spectral_slope"] is None for g in rep["groups"])
    assert rep["drift"][0]["metric"].startswith("brightness")  # the other metrics still rank normally
    assert len(rep["points"]) == 8 and all(abs(p["outlier"]) < 1e6 for p in rep["points"])


def test_tabular_profile_is_json_safe_with_degenerate_columns():
    df = pd.DataFrame(
        {
            "single": [1.0] + [np.nan] * 39,  # one value: std is NaN with ddof = 1
            "const": [2.0] * 40,
            "x": np.arange(40, dtype=float),
            "y": np.arange(40, dtype=float) * 2,
        }
    )
    rep = tabular_analysis.profile(df, target="y")
    json.dumps(rep, allow_nan=False)
    cols = {c["name"]: c for c in rep["columns"]}
    assert cols["single"]["std"] == 0.0 and cols["single"]["mean"] == 1.0 and cols["single"]["outlier_ratio"] == 0
    assert cols["const"]["std"] == 0.0 and "const" in " ".join(r["text"] for r in rep["recommendations"])
    json.dumps(tabular_analysis.compact(rep), allow_nan=False)


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
