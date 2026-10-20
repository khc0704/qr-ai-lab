"""spectrum.pls — partial least squares on spectra (chemometrics standard): PLS regression for a measured value
(CD, thickness, concentration) and PLS-DA (PLS scores + logistic regression) for classification.

Inference: ``predict`` (value / class + probabilities), ``embed`` (the PLS scores). The VIP scores say which
wavelengths carry the prediction (``report/vip.csv``). CPU only, no weights, seconds to train.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import joblib
import numpy as np
from sklearn.cross_decomposition import PLSRegression

from trainer import jsonsafe
from trainer import metrics as M
from trainer.data.split import holdout
from trainer.dataset import Dataset
from trainer.log import info
from trainer.models.base import ArtifactOut, BaseInferencer, BaseTrainer, PredictResult
from trainer.models.sequence import as_windows


def _flat(X: np.ndarray) -> np.ndarray:
    return X.reshape(len(X), -1).astype(np.float64)


def vip_scores(pls: PLSRegression) -> np.ndarray:
    """Variable importance in projection (Wold): > 1 = the wavelength matters."""
    t = pls.x_scores_
    w = pls.x_weights_
    q = pls.y_loadings_
    p, h = w.shape
    ss = np.diag(t.T @ t @ q.T @ q).reshape(h, -1)
    total = ss.sum()
    wn = w / (np.linalg.norm(w, axis=0, keepdims=True) + 1e-12)
    return np.sqrt(p * ((wn**2) @ ss).ravel() / max(total, 1e-12))


class PLSTrainer(BaseTrainer):
    framework = "sklearn"
    inference_modes = ["predict", "embed"]

    def fit(self, ds: Dataset) -> None:
        if not ds.has_labels:
            raise ValueError("PLS 需要標籤欄位（spec.label：量測值或類別）")
        X = as_windows(ds.X)
        self.T, self.C = int(X.shape[1]), int(X.shape[2])
        F = _flat(X)
        n = len(F)
        want = int(self.params.get("n_components", 10))
        self.n_components = max(1, min(want, F.shape[1], n - 2))
        scale = bool(self.params.get("scale", False))
        self.classes: list[str] | None = None
        self.head = None
        if self.task == "classification":
            labels = np.asarray(ds.y).astype(str)
            self.classes = sorted(set(labels.tolist()))
            index = {c: i for i, c in enumerate(self.classes)}
            y = np.array([index[v] for v in labels])
            tr, va = holdout(n, labels, "classification")
            self.pls = self._fit_pls(F[tr], np.eye(len(self.classes))[y[tr]], scale)
            self.head = self._head().fit(self.pls.transform(F[tr]), y[tr])
            proba = self.head.predict_proba(self.pls.transform(F[va]))
            self.metrics = M.classification(y[va], proba.argmax(axis=1), proba)
            self._Y = np.eye(len(self.classes))[y]
        else:
            y = np.asarray(ds.y, dtype=float)
            tr, va = holdout(n, y, "regression")
            self.pls = self._fit_pls(F[tr], y[tr], scale)
            self.metrics = M.regression(y[va], self.pls.predict(F[va]).ravel())
            self._Y = y
        self._F, self._y, self._scale = F, y, scale
        self.meta.update({"n_components": self.n_components, "T": self.T, "C": self.C})
        scores = ", ".join(f"{k}={v:.4f}" for k, v in self.metrics.items())
        info(f"{self.family}: n_components={self.n_components} {scores}")
        self.ctx.progress(0.9, "evaluating")

    def _fit_pls(self, F: np.ndarray, Y: np.ndarray, scale: bool) -> PLSRegression:
        k = max(1, min(self.n_components, len(F) - 1, F.shape[1]))
        return PLSRegression(n_components=k, scale=scale).fit(F, Y)

    def _head(self):
        from sklearn.linear_model import LogisticRegression

        return LogisticRegression(C=float(self.params.get("C", 1.0)), max_iter=3000)

    def finalize(self, ds: Dataset) -> None:
        """Refit on every row (holdout metrics stay as reported)."""
        self.pls = self._fit_pls(self._F, self._Y, self._scale)
        if self.head is not None:
            self.head = self._head().fit(self.pls.transform(self._F), self._y)

    def export(self, out: Path) -> list[ArtifactOut]:
        model_dir = out / "model"
        model_dir.mkdir(parents=True, exist_ok=True)
        joblib.dump({"pls": self.pls, "head": self.head}, model_dir / "model.joblib")
        vip = vip_scores(self.pls)
        explained = (np.var(self.pls.x_scores_, axis=0) / max(np.var(self._F, axis=0).sum(), 1e-12)).tolist()
        meta = {
            "classes": self.classes,
            "task_type": self.task,
            "n_components": int(self.pls.n_components),
            "T": self.T,
            "C": self.C,
            "explained_x_variance": [round(float(v), 6) for v in explained],
            "top_vip": [int(i) for i in np.argsort(vip)[::-1][:20]],
            "metrics": self.metrics,
        }
        (model_dir / "metadata.json").write_text(jsonsafe.dumps(meta, indent=2), encoding="utf-8")
        rep = out / "report"
        rep.mkdir(parents=True, exist_ok=True)
        with (rep / "vip.csv").open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["position", "channel", "vip", *[f"loading_{k + 1}" for k in range(self.pls.n_components)]])
            for j in range(len(vip)):
                w.writerow([j // self.C, j % self.C, float(vip[j]), *[float(v) for v in self.pls.x_loadings_[j]]])
        return [
            ArtifactOut(
                name="pls",
                kind="model",
                path="model",
                framework=self.framework,
                metrics=self.metrics,
                metadata=meta,
            ),
            ArtifactOut(name="vip", kind="report", path="report/vip.csv", framework=self.framework),
        ]


class PLSInferencer(BaseInferencer):
    def load(self, model_path: Path, metadata: dict[str, Any]) -> None:
        blob = joblib.load(model_path / "model.joblib")
        self.pls: PLSRegression = blob["pls"]
        self.head = blob.get("head")
        local = model_path / "metadata.json"
        self.meta = {
            **(json.loads(local.read_text(encoding="utf-8")) if local.exists() else {}),
            **(metadata or {}),
        }
        self.classes: list[str] = list(self.meta.get("classes") or [])
        self.task = self.meta.get("task_type")

    def predict(self, ds: Dataset, mode: str, options: dict[str, Any], out: Path) -> PredictResult:
        out.mkdir(parents=True, exist_ok=True)
        X = as_windows(ds.X, int(self.meta.get("T") or 0) or None)
        F = _flat(X)
        ids = [str(i) for i in (ds.ids or range(len(F)))]
        if mode == "embed":
            scores = self.pls.transform(F)
            np.save(out / "embeddings.npy", scores)
            rows = [{"id": i, "embedding": [round(float(v), 6) for v in s]} for i, s in zip(ids, scores, strict=True)]
            art = ArtifactOut(name="embeddings", kind="report", path="output/embeddings.npy", framework="sklearn")
            return PredictResult(rows, {"mode": mode, "n": len(rows), "dim": int(scores.shape[1])}, [art])
        if self.head is not None and self.classes:
            proba = self.head.predict_proba(self.pls.transform(F))
            rows = []
            for n, i in enumerate(ids):
                j = int(proba[n].argmax())
                row = {"id": i, "prediction": self.classes[j], "confidence": float(proba[n][j])}
                if len(self.classes) <= 50:
                    row.update({f"proba_{c}": float(proba[n][m]) for m, c in enumerate(self.classes)})
                rows.append(row)
            counts: dict[str, int] = {}
            for r in rows:
                counts[r["prediction"]] = counts.get(r["prediction"], 0) + 1
            return PredictResult(rows, {"mode": "predict", "n": len(rows), "class_counts": counts})
        pred = self.pls.predict(F).ravel()
        rows = [{"id": i, "prediction": float(p)} for i, p in zip(ids, pred, strict=True)]
        return PredictResult(
            rows,
            {
                "mode": "predict",
                "n": len(rows),
                "mean": float(pred.mean()),
                "min": float(pred.min()),
                "max": float(pred.max()),
            },
        )
