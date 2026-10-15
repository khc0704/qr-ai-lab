from __future__ import annotations

import io
import zipfile

import numpy as np
import pandas as pd
import pytest
from PIL import Image

from qrlab_preprocess import Pipeline, catalog, validate
from qrlab_preprocess.preview import run_preview


def test_catalog_lists_ops_per_data_type():
    ids = {o["id"] for o in catalog("TABULAR")}
    assert {"tabular.impute", "tabular.standardize", "tabular.clip_outliers"} <= ids
    assert all("IMAGE" in o["data_types"] for o in catalog("IMAGE"))
    assert any(o["fitted"] for o in catalog("IMAGE")) and any(o["geometric"] for o in catalog("IMAGE"))


def test_validate_rejects_bad_steps():
    with pytest.raises(ValueError, match="未知的前處理"):
        validate("TABULAR", None, [{"op": "nope"}])
    with pytest.raises(ValueError, match="不適用於"):
        validate("TABULAR", None, [{"op": "image.resize"}])
    with pytest.raises(ValueError, match="座標"):
        validate("IMAGE", "detection", [{"op": "image.resize", "params": {"width": 64}}])
    with pytest.raises(ValueError, match="未知參數"):
        validate("TABULAR", None, [{"op": "tabular.impute", "params": {"foo": 1}}])
    with pytest.raises(ValueError, match="必須是"):
        validate("TABULAR", None, [{"op": "tabular.impute", "params": {"strategy": "magic"}}])
    assert validate("IMAGE", "classification", [{"op": "image.resize", "params": {"width": 64}}])


def test_tabular_fit_then_replay():
    df = pd.DataFrame({"a": [1.0, 2.0, None, 4.0, 100.0], "b": ["x", "y", "x", None, "x"], "y": [0, 1, 0, 1, 0]})
    steps = [
        {"op": "tabular.impute", "params": {"strategy": "median"}},
        {"op": "tabular.clip_outliers", "params": {"method": "iqr", "factor": 1.5, "action": "clip"}},
        {"op": "tabular.standardize"},
    ]
    pipe = Pipeline.from_spec("TABULAR", steps, protected=["y"])
    out = pipe.fit_transform(df)
    assert out["a"].isna().sum() == 0 and out["b"].isna().sum() == 0 and out["y"].tolist() == df["y"].tolist()
    assert abs(out["a"].mean()) < 1e-6 and abs(out["a"].std() - 1) < 1e-6
    state = pipe.to_json()
    assert state[0]["state"]["values"]["a"] == 3.0 and state[0]["state"]["values"]["b"] == "x"  # median of 1,2,4,100
    replay = Pipeline.from_json("TABULAR", state, protected=["y"])
    new = replay.transform(pd.DataFrame({"a": [None, 2.0], "b": [None, "y"]}))
    assert new["a"].iloc[0] == out["a"].iloc[2]  # imputed with the training median, scaled with the training stats


def test_tabular_row_filters_keep_labels_aligned():
    df = pd.DataFrame({"a": [1, 2, 3, 3, None], "line": ["A", "B", "A", "A", "A"], "y": [1, 2, 3, 3, 5]})
    steps = [
        {"op": "tabular.filter_rows", "params": {"column": "line", "operator": "==", "value": "A"}},
        {"op": "tabular.drop_missing"},
        {"op": "tabular.drop_duplicates"},
    ]
    out = Pipeline.from_spec("TABULAR", steps, protected=["y"]).fit_transform(df)
    assert out["y"].tolist() == [1, 3] and out["a"].tolist() == [1, 3]


def test_text_ops():
    df = pd.DataFrame(
        {"text": ["  Hello   WORLD http://x.y  ", "", "機台 123 警報!", "機台 123 警報!"], "label": list("abcc")}
    )
    steps = [
        {"op": "text.lowercase"},
        {"op": "text.remove_urls"},
        {"op": "text.remove_numbers"},
        {"op": "text.strip_whitespace"},
        {"op": "text.drop_empty"},
        {"op": "text.dedupe"},
    ]
    out = Pipeline.from_spec("TEXT", steps, text_column="text").fit_transform(df)
    assert out["text"].tolist() == ["hello world", "機台 警報!"] and out["label"].tolist() == ["a", "c"]


def test_sequence_ops_and_msc_state():
    rng = np.random.default_rng(0)
    t = np.linspace(0, 1, 100)
    X = np.stack(
        [np.exp(-((t - 0.5) ** 2) / 0.01) * (1 + 0.3 * i) + 0.2 * i + rng.normal(0, 0.01, 100) for i in range(8)]
    ).astype(np.float32)
    steps = [
        {"op": "sequence.savgol", "params": {"window": 7, "polyorder": 2}},
        {"op": "sequence.baseline_poly", "params": {"degree": 1}},
        {"op": "sequence.msc"},
        {"op": "sequence.resample", "params": {"length": 50}},
        {"op": "sequence.snv"},
    ]
    pipe = Pipeline.from_spec("SPECTRUM", steps)
    out = pipe.fit_transform(X)
    assert out.shape == (8, 50, 1) and abs(out[0].mean()) < 1e-4
    state = pipe.to_json()
    assert len(state[2]["state"]["reference"]) == 100
    again = Pipeline.from_json("SPECTRUM", state).transform(X[:2])
    assert again.shape == (2, 50, 1) and np.allclose(again, out[:2], atol=1e-4)
    d = Pipeline.from_spec("SPECTRUM", [{"op": "sequence.derivative", "params": {"order": 1}}]).fit_transform(X)
    assert d.shape == (*X.shape[:2], 1)


def _img(seed: int, shift: int = 0) -> Image.Image:
    a = np.zeros((64, 64), np.uint8) + 30
    a[20 + shift : 40 + shift, 24 + shift : 44 + shift] = 220
    rng = np.random.default_rng(seed)
    a = np.clip(a.astype(int) + rng.integers(-5, 5, a.shape), 0, 255).astype(np.uint8)
    return Image.fromarray(a, mode="L")


def test_image_ops_and_alignment():
    images = [_img(0), _img(1, shift=6), _img(2, shift=-5)]
    steps = [{"op": "image.align"}, {"op": "image.autocontrast"}, {"op": "image.resize", "params": {"width": 32}}]
    pipe = Pipeline.from_spec("IMAGE", steps, task_type="classification")
    out = pipe.fit_transform(images)
    assert len(out) == 3 and out[0].size == (32, 32)
    ref = np.asarray(_img(0).resize((32, 32)), dtype=float)
    for im in out[1:]:
        corr = np.corrcoef(ref.ravel(), np.asarray(im, dtype=float).ravel())[0, 1]
        assert corr > 0.9, corr  # shifted squares are back on top of the reference
    state = pipe.to_json()
    assert "__png__" in state[0]["state"]["reference"]
    replay = Pipeline.from_json("IMAGE", state).transform([_img(3, shift=4)])
    assert replay[0].size == (32, 32)


def test_preview_payloads(tmp_path):
    csv = tmp_path / "d.csv"
    pd.DataFrame({"a": [1.0, None, 3.0, 50.0], "b": ["x", "y", "x", "y"], "y": [0, 1, 0, 1]}).to_csv(csv, index=False)
    r = run_preview(
        "TABULAR", csv, "csv", [{"op": "tabular.impute"}, {"op": "tabular.minmax"}], sample=3, spec={"target": "y"}
    )
    assert (
        r["before"]["row_count"] == 4
        and r["before"]["stats"][0]["missing"] == 1
        and r["after"]["stats"][0]["missing"] == 0
    )
    assert r["after"]["stats"][0]["max"] == 1.0 and len(r["after"]["rows"]) == 3 and r["steps"]
    zp = tmp_path / "imgs.zip"
    with zipfile.ZipFile(zp, "w") as z:
        for cls in ("good", "bad"):
            for i in range(3):
                buf = io.BytesIO()
                _img(i).save(buf, format="PNG")
                z.writestr(f"{cls}/{i}.png", buf.getvalue())
    r = run_preview(
        "IMAGE",
        zp,
        "image_folder",
        [{"op": "image.grayscale"}, {"op": "image.center_crop", "params": {"fraction": 0.5}}],
        sample=4,
    )
    assert len(r["before"]["images"]) == 4 and {i["id"].split("/")[0] for i in r["before"]["images"]} == {"good", "bad"}
    assert r["after"]["images"][0]["width"] == 32 and r["before"]["images"][0]["png_base64"]
    npy = tmp_path / "s.npy"
    np.save(npy, np.random.default_rng(0).normal(size=(10, 300)).astype(np.float32))
    r = run_preview("SPECTRUM", npy, "npy", [{"op": "sequence.snv"}], sample=2)
    assert r["after"]["stats"]["shape"] == [10, 300, 1] and len(r["after"]["curves"]) == 2
    with pytest.raises(ValueError):
        run_preview(
            "TABULAR",
            csv,
            "csv",
            [{"op": "tabular.filter_rows", "params": {"column": "zzz", "operator": "==", "value": "1"}}],
        )
