from __future__ import annotations

import io
import json
import zipfile

import numpy as np
import pandas as pd
from PIL import Image

from qrlab_preprocess import Pipeline
from qrlab_preprocess.process import run_full


def test_tabular_full_run_writes_csv_pipeline_and_summary(tmp_path):
    src = tmp_path / "wat.csv"
    pd.DataFrame({"x1": [1.0, None, 3.0, 50.0], "x2": [2.0, 3.0, None, 1.0], "yield_pct": [91, 88, 90, 70]}).to_csv(
        src, index=False
    )
    out = tmp_path / "out"
    summary = run_full(
        "TABULAR",
        src,
        "csv",
        [{"op": "tabular.impute", "params": {"strategy": "median"}}, {"op": "tabular.standardize"}],
        out,
        spec={"target": "yield_pct"},
    )
    df = pd.read_csv(out / "processed.csv")
    assert df.isna().sum().sum() == 0 and abs(df["x1"].mean()) < 1e-6 and list(df["yield_pct"]) == [91, 88, 90, 70]
    assert summary["before"]["rows"] == 4 and "processed.csv" in summary["files"]
    state = json.loads((out / "pipeline.json").read_text(encoding="utf-8"))
    replay = Pipeline.from_json("TABULAR", state["steps"], protected=["yield_pct"])
    again = replay.transform(pd.read_csv(src))
    assert np.allclose(again["x1"].to_numpy(), df["x1"].to_numpy())
    assert json.loads((out / "summary.json").read_text(encoding="utf-8"))["data_type"] == "TABULAR"


def test_spectrum_and_image_full_runs(tmp_path):
    src = tmp_path / "spec.csv"
    frame = pd.DataFrame(np.random.rand(6, 32).astype(np.float32), columns=[f"w{i}" for i in range(32)])
    frame.to_csv(src, index=False)
    out = tmp_path / "spec_out"
    summary = run_full("SPECTRUM", src, "csv", [{"op": "sequence.snv"}], out)
    X = np.load(out / "processed.npy")
    assert X.shape == (6, 32, 1) and (out / "processed.csv").exists() and summary["after"]["shape"] == [6, 32, 1]

    zpath = tmp_path / "imgs.zip"
    with zipfile.ZipFile(zpath, "w") as z:
        for i in range(3):
            buf = io.BytesIO()
            Image.new("RGB", (40, 30), (i * 40, 100, 200)).save(buf, format="PNG")
            z.writestr(f"ok/img{i}.png", buf.getvalue())
    out = tmp_path / "img_out"
    steps = [{"op": "image.resize", "params": {"width": 20, "height": 15}}]
    summary = run_full("IMAGE", zpath, "image_folder", steps, out)
    assert summary["after"]["images"] == 3
    assert Image.open(out / "images" / "ok" / "img1.png").size == (20, 15)
