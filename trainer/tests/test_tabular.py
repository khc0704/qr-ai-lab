from __future__ import annotations

import pytest

from tests.conftest import anomaly_frame, cls_frame, reg_frame
from trainer.dataset import Dataset
from trainer.models import registry

FAST = {"n_estimators": 60}


@pytest.mark.parametrize("fid", ["tabular.linear", "tabular.svm", "tabular.random_forest", "tabular.xgboost"])
def test_classification_roundtrip(tmp_path, ctx, fid):
    df = cls_frame()
    ds = Dataset("TABULAR", "classification", {"target": "label"}, X=df.drop(columns=["label"]), y=df["label"])
    ds.ids = [str(i) for i in range(len(df))]
    t = registry.create_trainer(fid, "classification", FAST, ctx)
    t.fit(ds)
    m = t.evaluate()
    assert m["f1_macro"] > 0.75 and "auroc" in m
    t.finalize(ds)
    arts = t.export(tmp_path)
    assert (tmp_path / "model" / "model.joblib").exists() and arts[0].kind == "model"
    inf = registry.create_inferencer(fid, ctx)
    inf.load(tmp_path / "model", {**arts[0].metadata, "task_type": "classification"})
    # inference input: extra column, missing feature, no target
    X = df.drop(columns=["label", "x2"]).assign(extra=1).head(10)
    res = inf.predict(
        Dataset("TABULAR", "classification", {}, X=X, ids=[str(i) for i in range(10)]), "predict", {}, tmp_path
    )
    assert len(res.rows) == 10 and {r["prediction"] for r in res.rows} <= {"pass", "fail"}
    assert 0 <= res.rows[0]["confidence"] <= 1 and "proba_pass" in res.rows[0]


@pytest.mark.parametrize("fid", ["tabular.linear", "tabular.random_forest", "tabular.xgboost"])
def test_regression_roundtrip(tmp_path, ctx, fid):
    df = reg_frame()
    ds = Dataset("TABULAR", "regression", {"target": "yield_pct"}, X=df.drop(columns=["yield_pct"]), y=df["yield_pct"])
    t = registry.create_trainer(fid, "regression", FAST, ctx)
    t.fit(ds)
    assert t.evaluate()["rmse"] < 1.0
    arts = t.export(tmp_path)
    inf = registry.create_inferencer(fid, ctx)
    inf.load(tmp_path / "model", {**arts[0].metadata, "task_type": "regression"})
    res = inf.predict(
        Dataset("TABULAR", "regression", {}, X=df.drop(columns=["yield_pct"]).head(5)), "predict", {}, tmp_path
    )
    assert len(res.rows) == 5 and 80 < res.rows[0]["prediction"] < 100


def test_isolation_forest_scores(tmp_path, ctx):
    df = anomaly_frame()
    ds = Dataset(
        "TABULAR", "anomaly_detection", {"target": "is_anomaly"}, X=df.drop(columns=["is_anomaly"]), y=df["is_anomaly"]
    )
    t = registry.create_trainer("tabular.isolation_forest", "anomaly_detection", {"n_estimators": 100}, ctx)
    t.fit(ds)
    m = t.evaluate()
    assert m["auroc"] > 0.9 and m["threshold"] > 0
    arts = t.export(tmp_path)
    inf = registry.create_inferencer("tabular.isolation_forest", ctx)
    inf.load(tmp_path / "model", {**arts[0].metadata, "task_type": "anomaly_detection"})
    res = inf.predict(
        Dataset("TABULAR", "anomaly_detection", {}, X=df.drop(columns=["is_anomaly"])), "score", {}, tmp_path
    )
    flagged = {r["id"] for r in res.rows if r["is_anomaly"]}
    assert res.summary["flagged"] >= 20 and len(flagged & {str(i) for i in range(475, 500)}) >= 20


def test_text_linear_tfidf(tmp_path, ctx):
    import pandas as pd

    rows = (
        [("機台溫度過高 警報", "alarm")] * 40 + [("例行保養完成 正常", "info")] * 40 + [("晶圓破片 停機", "alarm")] * 20
    )
    df = pd.DataFrame(rows, columns=["text", "label"])
    ds = Dataset(
        "TEXT", "classification", {"text_column": "text", "label_column": "label"}, X=df["text"], y=df["label"]
    )
    t = registry.create_trainer("tabular.linear", "classification", {}, ctx)
    t.fit(ds)
    assert t.evaluate()["f1_macro"] > 0.9
    arts = t.export(tmp_path)
    inf = registry.create_inferencer("tabular.linear", ctx)
    inf.load(tmp_path / "model", {**arts[0].metadata, "task_type": "classification"})
    res = inf.predict(
        Dataset("TEXT", "classification", {}, X=pd.Series(["溫度 警報", "保養 正常"])), "predict", {}, tmp_path
    )
    assert [r["prediction"] for r in res.rows] == ["alarm", "info"]
