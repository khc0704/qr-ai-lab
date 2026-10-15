"""Base classes shared by every model family.

A family implements a Trainer (fit → evaluate → export) and an Inferencer (load → predict). The runtime never
knows about frameworks; it only moves Datasets in and artifacts out. Registry ids must match
backend/app/catalog/model_catalog.yaml.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from trainer.dataset import Dataset


class Cancelled(Exception):
    """SIGTERM received (user cancel / admin force stop / timeout)."""


class Pruned(Exception):
    """AutoML decided this trial is not worth finishing."""


@dataclass
class Context:
    """What a trainer may use: resources, scratch dir, zoo resolver, progress / epoch callbacks."""

    work_dir: Path
    cpu: int = 1
    gpu: int = 0
    zoo: Callable[[str], Path] | None = None  # weight id → local path (raises if missing)
    on_progress: Callable[[float, str | None], None] | None = None
    on_epoch: Callable[[int, dict[str, float]], None] | None = None
    cancelled: bool = False

    def check(self) -> None:
        if self.cancelled:
            raise Cancelled()

    def progress(self, frac: float, stage: str | None = None) -> None:
        self.check()
        if self.on_progress:
            self.on_progress(max(0.0, min(1.0, frac)), stage)

    def epoch(self, epoch: int, metrics: dict[str, float]) -> None:
        """Report per-epoch metrics; AutoML may raise Pruned from here."""
        self.check()
        if self.on_epoch:
            self.on_epoch(epoch, metrics)

    def weight(self, weight_id: str) -> Path:
        if self.zoo is None:
            raise FileNotFoundError(f"model zoo is not mounted; cannot load weights '{weight_id}'")
        return self.zoo(weight_id)

    @property
    def device(self) -> str:
        if self.gpu > 0:
            try:
                import torch

                if torch.cuda.is_available():
                    return "cuda"
            except ImportError:
                pass
        return "cpu"

    @property
    def workers(self) -> int:
        return max(0, min(self.cpu, int(os.environ.get("MAX_DATALOADER_WORKERS", "8"))))


@dataclass
class ArtifactOut:
    """One file / directory under the job output dir to register with the backend."""

    name: str
    kind: str  # model | weights | preprocessor | report | metrics
    path: str  # relative to the job output dir
    framework: str
    metrics: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None
    set_default: bool = False


@dataclass
class PredictResult:
    rows: list[dict[str, Any]]
    summary: dict[str, Any] = field(default_factory=dict)
    extra_artifacts: list[ArtifactOut] = field(default_factory=list)


class BaseTrainer:
    framework: str = ""
    inference_modes: list[str] = ["predict"]

    def __init__(self, family: str, task: str | None, params: dict[str, Any], ctx: Context) -> None:
        self.family = family
        self.task = task
        self.params = params
        self.ctx = ctx
        self.metrics: dict[str, float] = {}
        self.meta: dict[str, Any] = {}

    # -- lifecycle ---------------------------------------------------------------------------
    def fit(self, ds: Dataset) -> None:
        raise NotImplementedError

    def evaluate(self) -> dict[str, float]:
        """Metrics on the holdout split (computed during fit)."""
        return dict(self.metrics)

    def finalize(self, ds: Dataset) -> None:
        """Called once on the winning trainer before export (e.g. refit on train + validation)."""

    def export(self, out: Path) -> list[ArtifactOut]:
        raise NotImplementedError

    # -- helpers -----------------------------------------------------------------------------
    def metadata(self, ds: Dataset, **extra: Any) -> dict[str, Any]:
        return {
            "family": self.family,
            "framework": self.framework,
            "task_type": self.task,
            "data_type": ds.data_type,
            "inference_modes": list(self.inference_modes),
            "params": _jsonable(self.params),
            "spec": {k: v for k, v in ds.spec.items() if k not in ("columns",)},
            "n_train": len(ds),
            **self.meta,
            **extra,
        }


class BaseInferencer:
    def __init__(self, family: str, ctx: Context) -> None:
        self.family = family
        self.ctx = ctx
        self.meta: dict[str, Any] = {}

    def load(self, model_path: Path, metadata: dict[str, Any]) -> None:
        raise NotImplementedError

    def predict(self, ds: Dataset, mode: str, options: dict[str, Any], out: Path) -> PredictResult:
        raise NotImplementedError


def _jsonable(v: Any) -> Any:
    try:
        import numpy as np

        if isinstance(v, np.generic):
            return v.item()
    except ImportError:
        pass
    if isinstance(v, dict):
        return {k: _jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    if isinstance(v, Path):
        return str(v)
    return v
