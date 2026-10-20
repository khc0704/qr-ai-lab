"""spectrum.pls: PLS regression and PLS-DA on synthetic spectra."""

from __future__ import annotations

import numpy as np
import pytest

from trainer.dataset import Dataset
from trainer.models import registry
from trainer.models.spectrum import vip_scores


def _spectra(n: int, T: int = 120, seed: int = 0):
    rng = np.random.default_rng(seed)
    x = np.linspace(0, 1, T)
    thickness = rng.uniform(10, 50, size=n)
    X = np.stack([np.exp(-((x - 0.3) ** 2) / 0.01) * (th / 20) + 0.2 * np.sin(8 * x * th / 30) for th in thickness])
    X += rng.normal(scale=0.01, size=X.shape)
    return X.astype(np.float32), thickness


def test_pls_regression_roundtrip(tmp_path, ctx):
    X, y = _spectra(80)
    ds = Dataset("SPECTRUM", "regression", {"label": "thickness"}, X=X, y=y, ids=[str(i) for i in range(80)])
    t = registry.create_trainer("spectrum.pls", "regression", {"n_components": 6}, ctx)
    t.fit(ds)
    m = t.evaluate()
    assert m["r2"] > 0.9 and m["rmse"] < 4, m
    t.finalize(ds)
    arts = t.export(tmp_path / "out")
    assert {a.kind for a in arts} == {"model", "report"} and (tmp_path / "out" / "report" / "vip.csv").exists()
    meta = arts[0].metadata
    assert meta["n_components"] == 6 and meta["T"] == 120 and len(meta["top_vip"]) == 20
    assert len(vip_scores(t.pls)) == 120
    inf = registry.create_inferencer("spectrum.pls", ctx)
    inf.load(tmp_path / "out" / "model", meta)
    Xq, yq = _spectra(5, seed=9)
    res = inf.predict(Dataset("SPECTRUM", None, {}, X=Xq, ids=list("abcde")), "predict", {}, tmp_path / "p")
    assert len(res.rows) == 5 and abs(res.rows[0]["prediction"] - yq[0]) < 6
    # a different wavelength count is resampled onto the training length
    Xq2 = np.stack([np.interp(np.linspace(0, 1, 90), np.linspace(0, 1, 120), s) for s in Xq]).astype(np.float32)
    res = inf.predict(Dataset("SPECTRUM", None, {}, X=Xq2, ids=list("abcde")), "predict", {}, tmp_path / "p2")
    assert abs(res.rows[0]["prediction"] - yq[0]) < 8
    res = inf.predict(Dataset("SPECTRUM", None, {}, X=Xq, ids=list("abcde")), "embed", {}, tmp_path / "p3")
    assert len(res.rows[0]["embedding"]) == 6 and res.summary["dim"] == 6


def test_pls_da_classification(tmp_path, ctx):
    X, y = _spectra(90, seed=3)
    labels = np.where(y < 25, "thin", np.where(y < 38, "mid", "thick"))
    ds = Dataset("SPECTRUM", "classification", {"label": "cls"}, X=X, y=labels, ids=[str(i) for i in range(90)])
    t = registry.create_trainer("spectrum.pls", "classification", {"n_components": 5}, ctx)
    t.fit(ds)
    assert t.evaluate()["f1_macro"] > 0.7
    t.finalize(ds)
    arts = t.export(tmp_path / "out")
    assert arts[0].metadata["classes"] == ["mid", "thick", "thin"]
    inf = registry.create_inferencer("spectrum.pls", ctx)
    inf.load(tmp_path / "out" / "model", arts[0].metadata)
    res = inf.predict(Dataset("SPECTRUM", None, {}, X=X[:4], ids=list("abcd")), "predict", {}, tmp_path / "p")
    assert {r["prediction"] for r in res.rows} <= {"thin", "mid", "thick"} and "proba_thin" in res.rows[0]
    assert res.summary["class_counts"]


def test_pls_needs_labels(ctx):
    X, _ = _spectra(10)
    t = registry.create_trainer("spectrum.pls", "regression", {}, ctx)
    with pytest.raises(ValueError, match="標籤"):
        t.fit(Dataset("SPECTRUM", "regression", {}, X=X))
