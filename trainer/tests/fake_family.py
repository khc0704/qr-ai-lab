"""A fast fake model family for AutoML tests: every "epoch" reports a metric and can sleep, so trials hit the
deadline / cancel paths deterministically. Registered into the registry by the tests themselves."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from trainer.dataset import Dataset
from trainer.models.base import ArtifactOut, BaseInferencer, BaseTrainer, Cancelled, PredictResult

FAMILY = "test.fake"


class FakeTrainer(BaseTrainer):
    framework = "fake"
    fits = 0  # how many fit() calls happened across trials (class level: a new trainer per trial)
    cancel_on_fit: int | None = None  # raise Cancelled (as SIGTERM would) during this fit (1-based)
    slow_from_fit: int | None = None  # from this fit (1-based) on, each epoch sleeps `sleep` seconds

    def fit(self, ds: Dataset) -> None:
        type(self).fits += 1
        n = type(self).fits
        epochs = int(self.params.get("epochs", 3))
        sleep = float(self.params.get("sleep", 0.05))
        for e in range(1, epochs + 1):
            if type(self).cancel_on_fit == n:
                raise Cancelled()
            if type(self).slow_from_fit is not None and n >= type(self).slow_from_fit:
                time.sleep(sleep)
            self.ctx.epoch(e, {"f1_macro": 0.5 + 0.1 * e})
            self.ctx.progress(e / epochs, "training")
        self.metrics = {"f1_macro": 0.5 + 0.1 * epochs, "accuracy": 0.9}
        self.meta["fit_number"] = n

    def export(self, out: Path) -> list[ArtifactOut]:
        model_dir = out / "model"
        model_dir.mkdir(parents=True, exist_ok=True)
        (model_dir / "model.json").write_text(json.dumps({"fit": self.meta.get("fit_number")}), encoding="utf-8")
        return [ArtifactOut(name="fake", kind="model", path="model", framework=self.framework, metrics=self.metrics)]


class FakeInferencer(BaseInferencer):
    def load(self, model_path: Path, metadata: dict[str, Any]) -> None:
        self.meta = metadata or {}

    def predict(self, ds: Dataset, mode: str, options: dict[str, Any], out: Path) -> PredictResult:
        return PredictResult([{"id": i, "prediction": "ok"} for i in ds.ids])


def reset(*, cancel_on_fit: int | None = None, slow_from_fit: int | None = None) -> None:
    FakeTrainer.fits = 0
    FakeTrainer.cancel_on_fit = cancel_on_fit
    FakeTrainer.slow_from_fit = slow_from_fit
