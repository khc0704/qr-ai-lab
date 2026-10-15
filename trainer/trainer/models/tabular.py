"""Classic ML families (sklearn / XGBoost): linear, SVM, random forest, XGBoost, isolation forest.

One Pipeline = preprocessor (impute + scale + one-hot, or TF-IDF for TEXT) + estimator, exported with joblib.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.pipeline import Pipeline

from trainer import metrics as M
from trainer.data.split import holdout
from trainer.data.tabular import preprocessor
from trainer.dataset import Dataset
from trainer.log import info
from trainer.models.base import ArtifactOut, BaseInferencer, BaseTrainer, PredictResult

NORMAL_LABELS = {"0", "normal", "good", "ok", "pass", "false", "negative"}


def _binary_anomaly_labels(y) -> np.ndarray:
    return np.array([0 if str(v).strip().lower() in NORMAL_LABELS else 1 for v in np.asarray(y)])


def _text_pipeline_head():
    from sklearn.feature_extraction.text import TfidfVectorizer

    return TfidfVectorizer(max_features=50000, ngram_range=(1, 2), sublinear_tf=True)


class TabularTrainer(BaseTrainer):
    def __init__(self, family: str, task: str | None, params: dict[str, Any], ctx) -> None:
        super().__init__(family, task, params, ctx)
        self.framework = "xgboost" if family == "tabular.xgboost" else "sklearn"
        self.inference_modes = ["score"] if family == "tabular.isolation_forest" else ["predict"]
        self.pipe: Pipeline | None = None
        self.classes: list[str] | None = None
        self.threshold: float | None = None
        self.feature_columns: list[str] = []

    # -- estimator -----------------------------------------------------------------------------
    def _estimator(self):
        p = self.params
        task = self.task
        n_jobs = max(1, self.ctx.cpu)
        seed = int(p.get("seed", 42))
        if self.family == "tabular.linear":
            if task == "classification":
                from sklearn.linear_model import LogisticRegression

                return LogisticRegression(C=float(p.get("C", 1.0)), max_iter=3000)
            from sklearn.linear_model import Ridge

            return Ridge(alpha=float(p.get("alpha", 1.0)))
        if self.family == "tabular.svm":
            kw = {
                "C": float(p.get("C", 1.0)),
                "kernel": p.get("kernel", "rbf"),
                "gamma": p.get("gamma", "scale"),
            }
            if task == "classification":
                from sklearn.svm import SVC

                return SVC(probability=True, random_state=seed, **kw)
            from sklearn.svm import SVR

            return SVR(**kw)
        if self.family == "tabular.random_forest":
            kw = {
                "n_estimators": int(p.get("n_estimators", 300)),
                "max_depth": p.get("max_depth"),
                "min_samples_leaf": int(p.get("min_samples_leaf", 1)),
                "n_jobs": n_jobs,
                "random_state": seed,
            }
            if task == "classification":
                from sklearn.ensemble import RandomForestClassifier

                return RandomForestClassifier(**kw)
            from sklearn.ensemble import RandomForestRegressor

            return RandomForestRegressor(**kw)
        if self.family == "tabular.xgboost":
            import xgboost as xgb

            kw = {
                "n_estimators": int(p.get("n_estimators", 500)),
                "learning_rate": float(p.get("learning_rate", 0.05)),
                "max_depth": int(p.get("max_depth", 6)),
                "min_child_weight": float(p.get("min_child_weight", 1)),
                "subsample": float(p.get("subsample", 0.8)),
                "colsample_bytree": float(p.get("colsample_bytree", 0.8)),
                "reg_lambda": float(p.get("reg_lambda", 1.0)),
                "n_jobs": n_jobs,
                "tree_method": "hist",
                "device": "cuda" if self.ctx.device == "cuda" else "cpu",
                "random_state": seed,
            }
            if task == "classification":
                return xgb.XGBClassifier(**kw)
            return xgb.XGBRegressor(**kw)
        if self.family == "tabular.isolation_forest":
            from sklearn.ensemble import IsolationForest

            contamination = p.get("contamination", "auto")
            return IsolationForest(
                n_estimators=int(p.get("n_estimators", 200)),
                max_samples=p.get("max_samples", "auto"),
                contamination=contamination if contamination == "auto" else float(contamination),
                n_jobs=n_jobs,
                random_state=seed,
            )
        raise KeyError(self.family)

    def _pipeline(self, ds: Dataset) -> Pipeline:
        pre = _text_pipeline_head() if ds.data_type == "TEXT" else preprocessor(ds.X, ds.spec)
        return Pipeline([("pre", pre), ("model", self._estimator())])

    # -- fit / evaluate ------------------------------------------------------------------------
    def _encode_y(self, y):
        if self.task == "classification":
            values = np.asarray(y).astype(str)
            self.classes = sorted(set(values.tolist()))
            index = {c: i for i, c in enumerate(self.classes)}
            return np.array([index[v] for v in values])
        if self.task == "anomaly_detection":
            return _binary_anomaly_labels(y) if y is not None else None
        return np.asarray(y, dtype=float)

    def fit(self, ds: Dataset) -> None:
        self.ctx.progress(0.05, "training")
        X = ds.X
        if isinstance(X, pd.DataFrame):
            self.feature_columns = [str(c) for c in X.columns]
        y = self._encode_y(ds.y) if ds.y is not None else None
        if self.task != "anomaly_detection" and y is None:
            raise ValueError("訓練需要標籤欄位（spec.target）")
        n = len(ds)
        self.pipe = self._pipeline(ds)
        if self.task == "anomaly_detection":
            self._fit_anomaly(X, y, n)
        else:
            tr, va = holdout(n, y, self.task)
            self._train_idx, self._val_idx = tr, va
            self.pipe.fit(_take(X, tr), y[tr])
            self.ctx.progress(0.8, "evaluating")
            self.metrics = self._score(_take(X, va), y[va])
        info(f"{self.family}: " + ", ".join(f"{k}={v:.4f}" for k, v in self.metrics.items()))
        self.ctx.progress(0.9, "evaluating")

    def _fit_anomaly(self, X, y, n: int) -> None:
        assert self.pipe is not None
        if y is not None and set(np.unique(y).tolist()) == {0, 1}:
            normal = np.flatnonzero(y == 0)
            tr, va_n = holdout(len(normal), None, None)
            train_idx = normal[tr]
            val_idx = np.concatenate([normal[va_n], np.flatnonzero(y == 1)])
            self.pipe.fit(_take(X, train_idx))
            scores = -self.pipe.decision_function(_take(X, val_idx))
            train_scores = -self.pipe.decision_function(_take(X, train_idx))
            self.threshold = float(np.percentile(train_scores, 99))
            self.metrics = M.anomaly(scores, y[val_idx], self.threshold)
        else:
            self.pipe.fit(X)
            scores = -self.pipe.decision_function(X)
            self.threshold = float(np.percentile(scores, 99))
            self.metrics = M.anomaly(scores, None, self.threshold)
        self.meta["threshold"] = self.threshold

    def _score(self, X_val, y_val) -> dict[str, float]:
        assert self.pipe is not None
        pred = self.pipe.predict(X_val)
        if self.task == "classification":
            proba = self.pipe.predict_proba(X_val) if hasattr(self.pipe, "predict_proba") else None
            return M.classification(y_val, pred, proba)
        return M.regression(y_val, pred)

    def finalize(self, ds: Dataset) -> None:
        """Refit on all rows (holdout metrics stay as reported)."""
        if self.task == "anomaly_detection" or self.pipe is None:
            return
        y = self._encode_y(ds.y)
        self.pipe.fit(ds.X, y)

    # -- export --------------------------------------------------------------------------------
    def export(self, out: Path) -> list[ArtifactOut]:
        assert self.pipe is not None
        model_dir = out / "model"
        model_dir.mkdir(parents=True, exist_ok=True)
        joblib.dump(self.pipe, model_dir / "model.joblib")
        importance = self._feature_importance()
        meta = {
            "classes": self.classes,
            "feature_columns": self.feature_columns,
            "threshold": self.threshold,
            "metrics": self.metrics,
        }
        (model_dir / "metadata.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        arts = [
            ArtifactOut(
                name=self.family.split(".")[-1],
                kind="model",
                path="model",
                framework=self.framework,
                metrics=self.metrics,
                metadata={**meta, **self.metadata_base()},
            )
        ]
        if importance:
            rep = out / "report"
            rep.mkdir(parents=True, exist_ok=True)
            (rep / "feature_importance.json").write_text(json.dumps(importance, ensure_ascii=False, indent=2))
            arts.append(
                ArtifactOut(
                    name="feature_importance",
                    kind="report",
                    path="report/feature_importance.json",
                    framework=self.framework,
                )
            )
        return arts

    def metadata_base(self) -> dict[str, Any]:
        return {
            "family": self.family,
            "framework": self.framework,
            "task_type": self.task,
            "inference_modes": self.inference_modes,
            "params": {
                k: (v if isinstance(v, (int, float, str, bool, type(None))) else str(v)) for k, v in self.params.items()
            },
        }

    def _feature_importance(self) -> list[dict[str, Any]] | None:
        assert self.pipe is not None
        model = self.pipe.named_steps["model"]
        try:
            names = list(self.pipe.named_steps["pre"].get_feature_names_out())
        except Exception:
            names = []
        values = None
        if hasattr(model, "feature_importances_"):
            values = np.asarray(model.feature_importances_, dtype=float)
        elif hasattr(model, "coef_"):
            coef = np.asarray(model.coef_, dtype=float)
            values = np.abs(coef).mean(axis=0) if coef.ndim == 2 else np.abs(coef)
        if values is None or not names or len(names) != len(values):
            return None
        order = np.argsort(values)[::-1][:50]
        return [{"feature": str(names[i]), "importance": float(values[i])} for i in order]


def _take(X, idx):
    if isinstance(X, (pd.DataFrame, pd.Series)):
        return X.iloc[idx]
    return X[idx]


class TabularInferencer(BaseInferencer):
    def load(self, model_path: Path, metadata: dict[str, Any]) -> None:
        self.pipe: Pipeline = joblib.load(model_path / "model.joblib")
        local = model_path / "metadata.json"
        self.meta = {
            **(json.loads(local.read_text(encoding="utf-8")) if local.exists() else {}),
            **(metadata or {}),
        }
        self.task = self.meta.get("task_type")

    def _prepare(self, ds: Dataset):
        X = ds.X
        cols = self.meta.get("feature_columns") or []
        if isinstance(X, pd.DataFrame) and cols:
            missing = [c for c in cols if c not in X.columns]
            if missing:
                info(f"inference: {len(missing)} feature columns missing, filled with NaN: {missing[:10]}")
                X = X.assign(**{c: np.nan for c in missing})
            X = X[cols]
        return X

    def predict(self, ds: Dataset, mode: str, options: dict[str, Any], out: Path) -> PredictResult:
        X = self._prepare(ds)
        ids = ds.ids or [str(i) for i in range(len(ds))]
        if mode == "score" or self.task == "anomaly_detection":
            scores = -self.pipe.decision_function(X)
            threshold = float(options.get("threshold") or self.meta.get("threshold") or np.percentile(scores, 99))
            rows = [
                {"id": i, "anomaly_score": float(s), "is_anomaly": bool(s > threshold)}
                for i, s in zip(ids, scores, strict=True)
            ]
            flagged = int(sum(r["is_anomaly"] for r in rows))
            return PredictResult(rows, {"mode": "score", "n": len(rows), "flagged": flagged, "threshold": threshold})
        pred = self.pipe.predict(X)
        classes = self.meta.get("classes")
        rows: list[dict[str, Any]] = []
        if self.task == "classification" and classes:
            proba = self.pipe.predict_proba(X) if hasattr(self.pipe, "predict_proba") else None
            for k, (i, p) in enumerate(zip(ids, pred, strict=True)):
                label = classes[int(p)] if int(p) < len(classes) else str(p)
                row: dict[str, Any] = {"id": i, "prediction": label}
                if proba is not None:
                    row["confidence"] = float(proba[k].max())
                    if options.get("include_probabilities", True) and len(classes) <= 50:
                        row.update({f"proba_{c}": float(proba[k][j]) for j, c in enumerate(classes)})
                rows.append(row)
            counts = pd.Series([r["prediction"] for r in rows]).value_counts().to_dict()
            return PredictResult(rows, {"mode": "predict", "n": len(rows), "class_counts": counts})
        for i, p in zip(ids, pred, strict=True):
            rows.append({"id": i, "prediction": float(p)})
        values = np.asarray(pred, dtype=float)
        return PredictResult(
            rows,
            {
                "mode": "predict",
                "n": len(rows),
                "mean": float(values.mean()),
                "min": float(values.min()),
                "max": float(values.max()),
            },
        )
