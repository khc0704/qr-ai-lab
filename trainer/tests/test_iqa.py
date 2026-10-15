"""Image-quality baseline: golden tool vs a blurrier / darker tool."""

from __future__ import annotations

import numpy as np
import pytest
from PIL import Image, ImageFilter

from trainer.dataset import Dataset
from trainer.models import registry
from trainer.models.iqa import METRICS, image_metrics


def _tool_images(root, name: str, n: int, blur: float, brightness: int, seed: int) -> list:
    rng = np.random.default_rng(seed)
    paths = []
    (root / name).mkdir(parents=True, exist_ok=True)
    for i in range(n):
        base = rng.normal(size=(96, 96)) * 40 + brightness
        # some structure: stripes + a few blobs, like a patterned wafer
        xx, yy = np.meshgrid(np.arange(96), np.arange(96))
        base += 30 * np.sin(xx / 6.0) + 20 * ((xx // 24 + yy // 24) % 2)
        im = Image.fromarray(np.clip(base, 0, 255).astype(np.uint8), mode="L")
        if blur:
            im = im.filter(ImageFilter.GaussianBlur(blur))
        p = root / name / f"{name}_{i}.png"
        im.save(p)
        paths.append(p)
    return paths


def test_metrics_are_sensitive_to_blur_and_brightness(tmp_path):
    sharp = _tool_images(tmp_path, "sharp", 1, 0.0, 120, 0)[0]
    blurry = _tool_images(tmp_path, "blurry", 1, 2.5, 120, 0)[0]
    dark = _tool_images(tmp_path, "dark", 1, 0.0, 60, 0)[0]
    ms, mb, md = (image_metrics(Image.open(p)) for p in (sharp, blurry, dark))
    assert set(ms) == set(METRICS)
    assert ms["sharpness_laplacian"] > mb["sharpness_laplacian"] * 3 and ms["hf_energy_ratio"] > mb["hf_energy_ratio"]
    assert ms["noise_sigma"] > mb["noise_sigma"] and md["brightness_mean"] < ms["brightness_mean"] - 40


def test_baseline_score_and_compare(tmp_path, ctx):
    golden = _tool_images(tmp_path / "train", "good", 40, 0.8, 120, 1)
    other = _tool_images(tmp_path / "train", "tool_b", 10, 2.5, 90, 2)
    ds = Dataset(
        "IMAGE",
        "anomaly_detection",
        {},
        X=golden + other,
        y=["normal"] * 40 + ["tool_b"] * 10,
        ids=[p.name for p in golden + other],
        root=tmp_path / "train",
    )
    t = registry.create_trainer("vision.image_quality", "anomaly_detection", {"z_threshold": 3.0}, ctx)
    t.fit(ds)
    m = t.evaluate()
    assert m["auroc"] > 0.95 and m["n_golden"] == 40
    arts = t.export(tmp_path / "out")
    assert {a.kind for a in arts} == {"model", "report"} and (
        tmp_path / "out" / "report" / "baseline_ranges.csv"
    ).exists()

    inf = registry.create_inferencer("vision.image_quality", ctx)
    inf.load(tmp_path / "out" / "model", arts[0].metadata)
    # same tool, new session → should pass
    same = _tool_images(tmp_path / "test_same", "same", 12, 0.8, 120, 3)
    res = inf.predict(
        Dataset("IMAGE", None, {}, X=same, ids=[p.name for p in same]), "compare", {}, tmp_path / "pred_same"
    )
    assert res.summary["verdict"] == "pass", res.summary
    assert res.summary["flagged"] <= 2 and len(res.summary["per_metric"]) == len(METRICS)
    # tuned tool that is still blurrier and darker → drift / fail on sharpness and brightness
    tuned = _tool_images(tmp_path / "test_tuned", "tuned", 12, 2.5, 90, 4)
    res = inf.predict(
        Dataset("IMAGE", None, {}, X=tuned, ids=[p.name for p in tuned]), "compare", {}, tmp_path / "pred_tuned"
    )
    assert res.summary["verdict"] in ("drift", "fail") and res.summary["verdict"] == "fail"
    bad = set(res.summary["failed_metrics"]) | set(res.summary["drifted_metrics"])
    assert "sharpness_laplacian" in bad and "brightness_mean" in bad
    assert (tmp_path / "pred_tuned" / "comparison.csv").exists() and res.extra_artifacts[0].kind == "report"
    assert res.rows[0]["out_of_range"] and res.summary["flagged"] >= 10
    # score mode: per-image verdicts only
    res = inf.predict(
        Dataset("IMAGE", None, {}, X=same[:3] + tuned[:3], ids=list("abcdef")), "score", {}, tmp_path / "pred_score"
    )
    assert [r["is_anomaly"] for r in res.rows[3:]] == [True, True, True] and "per_metric" not in res.summary


def test_requires_enough_golden_images(tmp_path, ctx):
    few = _tool_images(tmp_path, "good", 3, 0.5, 120, 5)
    t = registry.create_trainer("vision.image_quality", "anomaly_detection", {}, ctx)
    with pytest.raises(ValueError, match="至少 5 張"):
        t.fit(Dataset("IMAGE", "anomaly_detection", {}, X=few, ids=[p.name for p in few]))
