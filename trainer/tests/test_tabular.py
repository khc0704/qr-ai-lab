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


def test_xgboost_falls_back_to_cpu_on_a_shared_gpu(tmp_path):
    from trainer.models.base import Context

    class CudaContext(Context):
        @property
        def device(self) -> str:
            return "cuda"

    exclusive = CudaContext(work_dir=tmp_path, cpu=3, gpu=1)
    shared = CudaContext(work_dir=tmp_path, cpu=3, gpu=1, gpu_memory_mb=4096)
    est = registry.create_trainer("tabular.xgboost", "regression", {}, exclusive)._estimator()
    assert est.get_params()["device"] == "cuda"
    est = registry.create_trainer("tabular.xgboost", "regression", {}, shared)._estimator()
    assert est.get_params()["device"] == "cpu" and est.get_params()["n_jobs"] == 3
    cpu_only = Context(work_dir=tmp_path, cpu=2, gpu=0)
    est = registry.create_trainer("tabular.xgboost", "regression", {}, cpu_only)._estimator()
    assert est.get_params()["device"] == "cpu"


@pytest.mark.parametrize("task", ["classification", "regression"])
def test_catboost_roundtrip(tmp_path, ctx, task):
    pytest.importorskip("catboost")
    if task == "classification":
        df = cls_frame()
        target = "label"
    else:
        df = reg_frame()
        target = "yield_pct"
    ds = Dataset("TABULAR", task, {"target": target}, X=df.drop(columns=[target]), y=df[target])
    t = registry.create_trainer("tabular.catboost", task, {"iterations": 80}, ctx)
    assert t.framework == "catboost"
    t.fit(ds)
    m = t.evaluate()
    assert (m["f1_macro"] > 0.75) if task == "classification" else (m["rmse"] < 1.0)
    t.finalize(ds)
    arts = t.export(tmp_path)
    assert arts[0].framework == "catboost" and any(a.name == "feature_importance" for a in arts)
    inf = registry.create_inferencer("tabular.catboost", ctx)
    inf.load(tmp_path / "model", {**arts[0].metadata, "task_type": task})
    res = inf.predict(Dataset("TABULAR", task, {}, X=df.drop(columns=[target]).head(5)), "predict", {}, tmp_path)
    assert len(res.rows) == 5 and ("confidence" in res.rows[0]) == (task == "classification")


def test_tabpfn_estimator_reads_weights_from_the_zoo(tmp_path):
    pytest.importorskip("tabpfn")
    from trainer.models.base import Context
    from trainer.models.zoo import resolver

    zoo = tmp_path / "zoo"
    (zoo / "tabpfn-v2.5-classifier-v2.5_default.ckpt").parent.mkdir(parents=True)
    (zoo / "tabpfn-v2.5-classifier-v2.5_default.ckpt").write_bytes(b"")
    (zoo / "tabpfn-v2.5-regressor-v2.5_default.ckpt").write_bytes(b"")
    ctx = Context(
        work_dir=tmp_path,
        cpu=3,
        gpu=0,
        zoo=resolver(
            zoo,
            {
                "tabpfn-v2.5-classifier": "tabpfn-v2.5-classifier-v2.5_default.ckpt",
                "tabpfn-v2.5-regressor": "tabpfn-v2.5-regressor-v2.5_default.ckpt",
            },
        ),
    )
    t = registry.create_trainer("tabular.tabpfn", "classification", {"n_estimators": 4}, ctx)
    est = t._estimator()
    params = est.get_params()
    assert t.framework == "tabpfn" and type(est).__name__ == "TabPFNClassifier"
    assert params["model_path"].endswith("tabpfn-v2.5-classifier-v2.5_default.ckpt")
    assert params["device"] == "cpu" and params["n_estimators"] == 4 and params["n_preprocessing_jobs"] == 3
    est = registry.create_trainer("tabular.tabpfn", "regression", {}, ctx)._estimator()
    assert type(est).__name__ == "TabPFNRegressor" and est.get_params()["n_estimators"] == "auto"
    # no zoo → the usual "weights missing" message, before any download could be attempted
    bare = Context(work_dir=tmp_path, cpu=1, gpu=0)
    with pytest.raises(FileNotFoundError, match="model zoo"):
        registry.create_trainer("tabular.tabpfn", "classification", {}, bare)._estimator()
