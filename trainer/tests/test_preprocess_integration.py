"""Preprocessing travels with the model: fitted at train time, replayed on inference input."""

from __future__ import annotations

import json
import zipfile

import numpy as np
import pandas as pd
from PIL import Image

from tests.conftest import cls_frame, families_for_spec
from tests.test_runtime import FakeBackend, _env
from trainer import dataset, runtime


def test_tabular_preprocess_fit_then_replay(tmp_path, monkeypatch):
    input_dir, out1, out2 = tmp_path / "input", tmp_path / "out1", tmp_path / "out2"
    input_dir.mkdir()
    df = cls_frame()
    df.loc[::7, "x1"] = np.nan  # missing values the model cannot take without imputation
    df.to_csv(input_dir / "train.csv", index=False)
    steps = [
        {"op": "tabular.filter_rows", "params": {"column": "line", "operator": "in", "value": "A,B"}},
        {"op": "tabular.impute", "params": {"strategy": "median"}},
        {"op": "tabular.standardize"},
    ]
    spec = {
        "job_id": 9,
        "kind": "train",
        "project_slug": "demo",
        "data_type": "TABULAR",
        "task_type": "classification",
        "mode": "manual",
        "model_family": "tabular.linear",
        "config": {},
        "input": {"kind": "upload", "format": "csv", "spec": {"target": "label", "preprocess": steps}},
        "artifact": None,
        "resources": {"gpu": 0, "cpu": 1, "memory_mb": 512},
        "timeout_minutes": 10,
        "families": families_for_spec("tabular.linear"),
        "zoo_weights": {},
    }
    _env(monkeypatch, input_dir, out1, "train")
    backend = FakeBackend(spec)
    assert runtime.run(backend) == 0, backend.statuses[-1]
    model = next(a for a in backend.artifacts_ if a["kind"] == "model")
    # artifact metadata (returned by every artifact list) carries the steps only; the fitted state is a file
    listed = model["metadata"]["preprocess"]
    assert [s["op"] for s in listed] == [s["op"] for s in steps]
    assert all("state" not in s for s in listed) and [s["has_state"] for s in listed] == [False, True, True]
    fitted = json.loads((out1 / "model" / "preprocess.json").read_text())
    assert fitted[1]["state"]["values"]["x1"] is not None and "x1" in fitted[2]["state"]["stats"]
    assert fitted[2]["op"] == "tabular.standardize"

    # inference rows with a missing value are imputed with the training median and scaled the same way
    spec2 = {
        **spec,
        "kind": "inference",
        "mode": None,
        "config": {},
        "input": {
            "kind": "inline",
            "format": "json",
            "spec": {},
            "rows": [{"x1": None, "x2": -1.0, "line": "A"}, {"x1": 2.0, "x2": -1.0, "line": "B"}],
        },
        "artifact": {
            "id": 1,
            "name": "m",
            "version": 1,
            "model_family": "tabular.linear",
            "framework": "sklearn",
            "file": "model",
            "metadata": model["metadata"],
        },
    }
    (tmp_path / "input2").mkdir()
    _env(monkeypatch, tmp_path / "input2", out2, "inference", model_dir=out1)
    backend2 = FakeBackend(spec2)
    assert runtime.run(backend2) == 0, backend2.statuses[-1]
    preview = backend2.result_[0]["preview"]
    assert len(preview) == 2 and all(r["prediction"] in ("pass", "fail") for r in preview)


def test_image_preprocess_writes_transformed_tree(tmp_path):
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    with zipfile.ZipFile(input_dir / "imgs.zip", "w") as z:
        for cls in ("A", "B"):
            for i in range(3):
                p = tmp_path / f"{cls}{i}.png"
                Image.new("RGB", (80, 60), (10 * i, 100, 200)).save(p)
                z.write(p, f"{cls}/{i}.png")
    spec = {"preprocess": [{"op": "image.grayscale"}, {"op": "image.resize", "params": {"width": 40}}]}
    ds = dataset.load("IMAGE", "classification", input_dir, spec, tmp_path / "work")
    assert len(ds) == 6 and ds.has_labels and sorted(set(ds.y)) == ["A", "B"]
    assert all("pre" in p.parts for p in ds.X)
    im = Image.open(ds.X[0])
    assert im.size == (40, 30) and im.mode == "L"
    assert ds.preprocess and ds.preprocess[1]["op"] == "image.resize"
    # replay with the stored state produces the same geometry
    ds2 = dataset.load("IMAGE", "classification", input_dir, {}, tmp_path / "work2", preprocess_state=ds.preprocess)
    assert Image.open(ds2.X[0]).size == (40, 30)


def test_spectrum_preprocess_state(tmp_path):
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    rng = np.random.default_rng(0)
    pd.DataFrame(rng.normal(size=(20, 64)) + 5).to_csv(input_dir / "spectra.csv", index=False)
    spec = {"preprocess": [{"op": "sequence.msc"}, {"op": "sequence.standardize"}]}
    ds = dataset.load("SPECTRUM", "anomaly_detection", input_dir, spec, tmp_path / "work")
    assert ds.X.shape == (20, 64, 1) and abs(float(ds.X.mean())) < 1e-4
    assert len(ds.preprocess[0]["state"]["reference"]) == 64


def test_tabular_encode_fit_then_replay(tmp_path, monkeypatch):
    """Categorical encoding learns the category list at train time and replays it on inference rows, including a
    category the training data never had (all-zero one-hot row)."""
    input_dir, out1, out2 = tmp_path / "input", tmp_path / "out1", tmp_path / "out2"
    input_dir.mkdir()
    cls_frame().to_csv(input_dir / "train.csv", index=False)
    steps = [
        {"op": "tabular.encode", "params": {"columns": ["line"], "method": "onehot"}},
        {"op": "tabular.standardize", "params": {"columns": ["x1", "x2"]}},
    ]
    spec = {
        "job_id": 10,
        "kind": "train",
        "project_slug": "demo",
        "data_type": "TABULAR",
        "task_type": "classification",
        "mode": "manual",
        "model_family": "tabular.linear",
        "config": {},
        "input": {"kind": "upload", "format": "csv", "spec": {"target": "label", "preprocess": steps}},
        "artifact": None,
        "resources": {"gpu": 0, "cpu": 1, "memory_mb": 512},
        "timeout_minutes": 10,
        "families": families_for_spec("tabular.linear"),
        "zoo_weights": {},
    }
    _env(monkeypatch, input_dir, out1, "train")
    backend = FakeBackend(spec)
    assert runtime.run(backend) == 0, backend.statuses[-1]
    model = next(a for a in backend.artifacts_ if a["kind"] == "model")
    assert [s["has_state"] for s in model["metadata"]["preprocess"]] == [True, True]
    fitted = json.loads((out1 / "model" / "preprocess.json").read_text())
    assert fitted[0]["op"] == "tabular.encode" and fitted[0]["state"] == {"categories": {"line": ["A", "B"]}}
    # the model was trained on the encoded columns, not on the text column
    assert model["metadata"]["feature_columns"] == ["x1", "x2", "line__A", "line__B"]

    spec2 = {
        **spec,
        "kind": "inference",
        "mode": None,
        "config": {},
        "input": {
            "kind": "inline",
            "format": "json",
            "spec": {},
            "rows": [
                {"x1": 1.0, "x2": -1.0, "line": "A"},
                {"x1": 1.0, "x2": -1.0, "line": "C"},  # unseen category → all-zero one-hot row, still predicts
                {"x1": 1.0, "x2": -1.0, "line": None},
            ],
        },
        "artifact": {
            "id": 1,
            "name": "m",
            "version": 1,
            "model_family": "tabular.linear",
            "framework": "sklearn",
            "file": "model",
            "metadata": model["metadata"],
        },
    }
    (tmp_path / "input2").mkdir()
    _env(monkeypatch, tmp_path / "input2", out2, "inference", model_dir=out1)
    backend2 = FakeBackend(spec2)
    assert runtime.run(backend2) == 0, backend2.statuses[-1]
    preview = backend2.result_[0]["preview"]
    assert len(preview) == 3 and all(r["prediction"] in ("pass", "fail") for r in preview)
