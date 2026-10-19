from __future__ import annotations

import base64
import io
import json
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


def test_text_ops_pick_columns_and_keep_missing_values():
    # TABULAR frames may carry free-text columns: the ops take `columns`, skip protected ones and keep NaN as NaN
    df = pd.DataFrame(
        {"note": ["  Tool A  ", None, "TOOL b"], "owner": ["Amy", "BOB", None], "y": ["KEEP", "Me", "AS-IS"]}
    )
    steps = [{"op": "text.lowercase", "params": {"columns": ["note", "y"]}}, {"op": "text.strip_whitespace"}]
    out = Pipeline.from_spec("TABULAR", steps, protected=["y"]).fit_transform(df)
    assert out["note"].tolist()[0] == "tool a" and out["note"].tolist()[2] == "tool b"
    assert pd.isna(out["note"].iloc[1]) and pd.isna(out["owner"].iloc[2])
    assert out["owner"].tolist()[:2] == ["Amy", "BOB"]  # strip_whitespace with no columns → every text column
    assert out["y"].tolist() == ["KEEP", "Me", "AS-IS"]  # protected: never transformed
    assert {"text.lowercase", "text.replace_regex"} <= {o["id"] for o in catalog("TABULAR")}
    with pytest.raises(ValueError, match="找不到文字欄位"):
        Pipeline.from_spec("TABULAR", [{"op": "text.lowercase", "params": {"columns": ["nope"]}}]).fit_transform(df)
    # TEXT: drop_empty removes empty and missing texts, the label column stays aligned
    tdf = pd.DataFrame({"text": ["a", "", None, "a"], "label": [1, 2, 3, 4]})
    out = Pipeline.from_spec("TEXT", [{"op": "text.drop_empty"}, {"op": "text.dedupe"}]).fit_transform(tdf)
    assert out["text"].tolist() == ["a"] and out["label"].tolist() == [1]


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


CAT = pd.DataFrame(
    {
        "line": ["B", "A", None, "C", "A"],
        "grade": ["lo", "hi", "mid", "hi", None],
        "n": [1, 2, 3, 4, 5],
        "y": [0, 1, 0, 1, 0],
    }
)


def test_encode_label_sorted_codes_missing_stays_missing_and_replays():
    pipe = Pipeline.from_spec("TABULAR", [{"op": "tabular.encode"}], protected=["y"])
    out = pipe.fit_transform(CAT)
    # default columns = every non-numeric column except the protected ones; codes follow the sorted categories
    assert out["line"].tolist()[:2] == [1.0, 0.0] and np.isnan(out["line"].iloc[2]) and out["line"].iloc[3] == 2.0
    assert out["grade"].tolist()[:4] == [1.0, 0.0, 2.0, 0.0] and np.isnan(out["grade"].iloc[4])
    assert out["n"].tolist() == [1, 2, 3, 4, 5] and out["y"].tolist() == CAT["y"].tolist()
    state = pipe.to_json()
    assert state[0]["state"] == {"categories": {"line": ["A", "B", "C"], "grade": ["hi", "lo", "mid"]}}
    assert json.loads(json.dumps(state)) == state  # JSON-serialisable as stored with the model
    replay = Pipeline.from_json("TABULAR", state, protected=["y"])
    same = replay.transform(CAT)
    pd.testing.assert_frame_equal(same, out)
    new = replay.transform(pd.DataFrame({"line": ["C", "Z", None], "grade": ["mid", "mid", "mid"]}))
    assert new["line"].iloc[0] == 2.0 and np.isnan(new["line"].iloc[1]) and np.isnan(new["line"].iloc[2])
    assert new["grade"].tolist() == [2, 2, 2]  # no missing / unknown → integer column
    assert replay.step_warnings[0] == ["欄位 line：1 個值不在類別清單中（如 Z），依「未知類別」處理"]
    # unknown=minus_one gives unseen categories −1 while real missing values stay missing
    minus = Pipeline.from_spec("TABULAR", [{"op": "tabular.encode", "params": {"unknown": "minus_one"}}])
    minus.fit_transform(CAT.drop(columns=["y"]))
    new = Pipeline.from_json("TABULAR", minus.to_json()).transform(pd.DataFrame({"line": ["Z", None, "A"]}))
    assert new["line"].iloc[0] == -1.0 and np.isnan(new["line"].iloc[1]) and new["line"].iloc[2] == 0.0
    # numeric-looking categories sort numerically and match across str / int / float
    pipe = Pipeline.from_spec("TABULAR", [{"op": "tabular.encode", "params": {"columns": ["k"]}}])
    assert pipe.fit_transform(pd.DataFrame({"k": ["10", "2", "x"]}))["k"].tolist() == [1, 0, 2]
    again = Pipeline.from_json("TABULAR", pipe.to_json()).transform(pd.DataFrame({"k": [2.0, 10]}))
    assert again["k"].tolist() == [0, 1]


def test_encode_onehot_columns_and_replay():
    steps = [{"op": "tabular.encode", "params": {"columns": ["line"], "method": "onehot"}}]
    pipe = Pipeline.from_spec("TABULAR", steps, protected=["y"])
    out = pipe.fit_transform(CAT)
    assert list(out.columns) == ["line__A", "line__B", "line__C", "grade", "n", "y"]  # in place of the original
    assert out["line__A"].tolist() == [0, 1, 0, 0, 1] and out["line__C"].tolist() == [0, 0, 0, 1, 0]
    assert out.loc[2, ["line__A", "line__B", "line__C"]].tolist() == [0, 0, 0]  # missing → all zero
    replay = Pipeline.from_json("TABULAR", pipe.to_json(), protected=["y"])
    new = replay.transform(pd.DataFrame({"line": ["C", "Z", None], "n": [1, 2, 3]}))
    assert list(new.columns) == ["line__A", "line__B", "line__C", "n"]
    assert new[["line__A", "line__B", "line__C"]].to_numpy().tolist() == [[0, 0, 1], [0, 0, 0], [0, 0, 0]]
    pd.testing.assert_frame_equal(replay.transform(CAT), out)


def test_encode_ordinal_uses_explicit_order():
    steps = [{"op": "tabular.encode", "params": {"columns": ["grade"], "method": "ordinal", "order": "lo,mid,hi"}}]
    pipe = Pipeline.from_spec("TABULAR", steps, protected=["y"])
    out = pipe.fit_transform(CAT)
    assert out["grade"].tolist()[:4] == [0.0, 2.0, 1.0, 2.0] and np.isnan(out["grade"].iloc[4])
    assert pipe.to_json()[0]["state"] == {"categories": {"grade": ["lo", "mid", "hi"]}}
    assert pipe.to_json()[0]["params"]["order"] == ["lo", "mid", "hi"]
    new = Pipeline.from_json("TABULAR", pipe.to_json()).transform(pd.DataFrame({"grade": ["hi", "huge"]}))
    assert new["grade"].iloc[0] == 2.0 and np.isnan(new["grade"].iloc[1])  # outside the order → missing
    with pytest.raises(ValueError, match="順序"):
        Pipeline.from_spec("TABULAR", [{"op": "tabular.encode", "params": {"method": "ordinal"}}]).fit_transform(CAT)
    with pytest.raises(ValueError, match="重複"):
        Pipeline.from_spec(
            "TABULAR", [{"op": "tabular.encode", "params": {"method": "ordinal", "order": ["a", "a"]}}]
        ).fit_transform(CAT)


def test_encode_rejects_high_cardinality_and_unknown_columns():
    with pytest.raises(ValueError, match=r"超過上限 2.*移除欄位"):
        Pipeline.from_spec("TABULAR", [{"op": "tabular.encode", "params": {"max_categories": 2}}]).fit_transform(CAT)
    with pytest.raises(ValueError, match="找不到欄位"):
        Pipeline.from_spec("TABULAR", [{"op": "tabular.encode", "params": {"columns": ["nope"]}}]).fit_transform(CAT)
    desc = next(o for o in catalog("TABULAR") if o["id"] == "tabular.encode")
    assert (
        desc["label"] == "類別編碼"
        and desc["fitted"]
        and {p["name"] for p in desc["params"]}
        == {
            "columns",
            "method",
            "order",
            "unknown",
            "max_categories",
        }
    )


def test_to_numeric_warns_when_a_column_is_really_categorical():
    df = pd.DataFrame({"line": ["A", "B", "A"], "v": [" 1.5", "2", "3e1"], "w": ["1", "x", "2"]})
    pipe = Pipeline.from_spec("TABULAR", [{"op": "tabular.to_numeric"}, {"op": "tabular.impute"}])
    out = pipe.fit_transform(df)
    assert out["v"].tolist() == [1.5, 2.0, 30.0] and out["line"].isna().sum() == 0  # imputed after the warning
    report = pipe.report()
    assert [r["op"] for r in report] == ["tabular.to_numeric", "tabular.impute"]
    assert report[0]["label"] == "文字數字轉成數值" and report[1]["warnings"] == []
    assert report[0]["warnings"] == [
        "欄位 line：100% 的值無法轉成數字，會變成缺值；若這是類別欄請改用「類別編碼」",
        "欄位 w：33% 的值無法轉成數字，會變成缺值；若這是類別欄請改用「類別編碼」",
    ]
    assert pipe.warnings() == ["步驟 1（文字數字轉成數值）" + m for m in report[0]["warnings"]]
    # exactly one of three values fails: 33% > 20% → warning; none fail → no warning
    pipe = Pipeline.from_spec("TABULAR", [{"op": "tabular.to_numeric", "params": {"columns": ["w"]}}])
    pipe.fit_transform(df)
    assert pipe.step_warnings[0] and "欄位 w：33%" in pipe.step_warnings[0][0]
    pipe = Pipeline.from_spec("TABULAR", [{"op": "tabular.to_numeric", "params": {"columns": ["v"]}}])
    pipe.fit_transform(df)
    assert pipe.step_warnings == [[]] and pipe.warnings() == []
    desc = next(o for o in catalog("TABULAR") if o["id"] == "tabular.to_numeric")
    assert "類別編碼" in desc["description"] and "以文字儲存的數字" in desc["description"]


def test_preview_column_stats_and_step_details(tmp_path):
    csv = tmp_path / "d.csv"
    pd.DataFrame(
        {
            "a": [1.0, None, 3.0, 50.0],
            "line": ["x", "y", "x", None],
            "flag": [True, False, True, True],
            "y": [0, 1, 0, 1],
        }
    ).to_csv(csv, index=False)
    onehot = [{"op": "tabular.encode", "params": {"method": "onehot"}}]
    r = run_preview("TABULAR", csv, "csv", onehot, spec={"target": "y"})
    assert r["rows_in"] == 4 and r["rows_out"] == 4
    cin = {c["name"]: c for c in r["columns_in"]}
    assert cin["a"]["dtype"] == "number" and cin["a"]["missing"] == 1 and cin["a"]["missing_ratio"] == 0.25
    assert cin["a"]["min"] == 1.0 and cin["a"]["max"] == 50.0 and cin["a"]["mean"] == 18.0 and cin["a"]["unique"] == 3
    assert cin["line"]["dtype"] == "text" and cin["line"]["unique"] == 2 and cin["line"]["min"] is None
    assert cin["line"]["top"] == [{"value": "x", "count": 2}, {"value": "y", "count": 1}]
    assert cin["flag"]["dtype"] == "bool" and cin["y"]["dtype"] == "number"
    assert [c["name"] for c in r["columns_out"]] == ["a", "line__x", "line__y", "flag", "y"]
    assert r["step_details"] == [
        {
            "op": "tabular.encode",
            "label": "類別編碼",
            "params": {"columns": [], "method": "onehot", "order": [], "unknown": "missing", "max_categories": 200},
            "fitted": True,
            "warnings": [],
        }
    ]
    assert r["warnings"] == [] and r["before"]["row_count"] == 4 and r["steps"]  # original fields still there
    steps = [{"op": "tabular.to_numeric"}, {"op": "tabular.drop_missing"}]
    r = run_preview("TABULAR", csv, "csv", steps, spec={"target": "y"})
    assert r["step_details"][0]["warnings"] == [
        "欄位 line：100% 的值無法轉成數字，會變成缺值；若這是類別欄請改用「類別編碼」"
    ]
    assert r["warnings"] == ["步驟 1（文字數字轉成數值）" + r["step_details"][0]["warnings"][0]]
    assert r["rows_in"] == 4 and r["rows_out"] == 0 and r["columns_out"][1]["dtype"] == "number"
    npy = tmp_path / "s.npy"
    np.save(npy, np.zeros((4, 16), np.float32))
    r = run_preview("SPECTRUM", npy, "npy", [{"op": "sequence.snv"}])
    assert r["columns_in"] is None and r["rows_in"] is None and r["step_details"][0]["op"] == "sequence.snv"


def test_image_preview_thumbnail_size_and_selection(tmp_path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for folder in ("a", "b"):
            for k in range(3):
                b = io.BytesIO()
                Image.new("L", (400, 300), color=40 * k + 20).save(b, format="PNG")
                z.writestr(f"{folder}/img{k}.png", b.getvalue())
    path = tmp_path / "imgs.zip"
    path.write_bytes(buf.getvalue())
    out = run_preview("IMAGE", path, "zip", [], sample=16, thumb=64)
    images = out["before"]["images"]
    assert 1 < len(images) <= 16 and images[0]["width"] == 400  # original size is reported …
    thumb = Image.open(io.BytesIO(base64.b64decode(images[0]["png_base64"])))
    assert max(thumb.size) == 64  # … while the thumbnail honours `thumb`
    # the lightbox asks for one entry at full thumbnail size; big thumbnails cap the count
    out = run_preview("IMAGE", path, "zip", [{"op": "image.grayscale"}], thumb=1024, image_ids=["b/img2.png"])
    assert [im["id"] for im in out["before"]["images"]] == ["b/img2.png"]
    assert max(Image.open(io.BytesIO(base64.b64decode(out["after"]["images"][0]["png_base64"]))).size) == 400
    assert len(run_preview("IMAGE", path, "zip", [], sample=16, thumb=1024)["before"]["images"]) == 2
    with pytest.raises(ValueError, match="找不到指定的影像"):
        run_preview("IMAGE", path, "zip", [], image_ids=["nope.png"])
