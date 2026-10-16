"""End-to-end inside the trainer process: fake backend, real files, AutoML train → artifacts → inference."""

from __future__ import annotations

import json
from pathlib import Path

from tests.conftest import cls_frame, families_for_spec
from trainer import runtime


class FakeBackend:
    def __init__(self, spec: dict) -> None:
        self._spec = spec
        self.statuses: list[dict] = []
        self.metrics_: list[dict] = []
        self.artifacts_: list[dict] = []
        self.result_: tuple | None = None

    def spec(self) -> dict:
        return self._spec

    def status(self, **kw) -> None:
        self.statuses.append(kw)

    def metrics(self, metrics, *, epoch=None, trial=None, leaderboard_row=None, retry="short") -> None:
        self.metrics_.append({"metrics": metrics, "trial": trial, "leaderboard_row": leaderboard_row, "retry": retry})

    def artifact(self, **kw) -> dict:
        self.artifacts_.append(kw)
        return {"id": len(self.artifacts_), "version": 1}

    def result(self, result=None, output_path=None, *, retry="long") -> None:
        self.result_ = (result, output_path)


def _env(monkeypatch, input_dir: Path, output_dir: Path, kind: str, model_dir: Path | None = None) -> None:
    monkeypatch.setenv("JOB_ID", "7")
    monkeypatch.setenv("JOB_KIND", kind)
    monkeypatch.setenv("JOB_TOKEN", "t")
    monkeypatch.setenv("BACKEND_URL", "http://unused")
    monkeypatch.setenv("JOB_INPUT_DIR", str(input_dir))
    monkeypatch.setenv("JOB_OUTPUT_DIR", str(output_dir))
    monkeypatch.setenv("JOB_MODEL_DIR", str(model_dir) if model_dir else "")
    monkeypatch.setenv("MODEL_ZOO_ROOT", "")


def test_automl_train_then_inference(tmp_path, monkeypatch):
    input_dir, out1, out2 = tmp_path / "input", tmp_path / "out1", tmp_path / "out2"
    input_dir.mkdir()
    cls_frame().to_csv(input_dir / "train.csv", index=False)
    spec = {
        "job_id": 7,
        "kind": "train",
        "project_slug": "demo",
        "data_type": "TABULAR",
        "task_type": "classification",
        "mode": "auto",
        "model_family": None,
        "config": {
            "search": {
                "candidates": ["tabular.random_forest", "tabular.linear"],
                "metric": "f1_macro",
                "direction": "maximize",
                "max_trials": 3,
                "time_budget_minutes": 5,
            }
        },
        "input": {"kind": "upload", "format": "csv", "spec": {"target": "label"}},
        "artifact": None,
        "resources": {"gpu": 0, "cpu": 2, "memory_mb": 1024},
        "timeout_minutes": 10,
        "families": families_for_spec("tabular.random_forest", "tabular.linear"),
        "zoo_weights": {},
    }
    _env(monkeypatch, input_dir, out1, "train")
    backend = FakeBackend(spec)
    assert runtime.run(backend) == 0
    assert backend.statuses[-1]["status"] == "succeeded" and backend.statuses[-1]["progress"] == 100
    rows = [m["leaderboard_row"] for m in backend.metrics_ if m["leaderboard_row"]]
    assert len(rows) == 3 and all(r["family"] in ("tabular.random_forest", "tabular.linear") for r in rows)
    kinds = [a["kind"] for a in backend.artifacts_]
    assert "model" in kinds and "metrics" in kinds
    model = next(a for a in backend.artifacts_ if a["kind"] == "model")
    assert model["path"] == "model" and model["metadata"]["family"] == backend.result_[0]["model_family"]
    assert (out1 / "model" / "model.joblib").exists() and not (out1 / "_work").exists()
    assert json.loads((out1 / "metrics" / "metrics.json").read_text())["n_trials"] == 3

    # inference with inline rows against the exported model dir
    spec2 = {
        **spec,
        "kind": "inference",
        "mode": None,
        "model_family": model["metadata"]["family"],
        "config": {},
        "input": {
            "kind": "inline",
            "format": "json",
            "spec": {},
            "rows": [{"x1": 2.0, "x2": -1.0, "line": "A"}, {"x1": -2.0, "x2": 1.0, "line": "B"}],
        },
        "artifact": {
            "id": 1,
            "name": "m",
            "version": 1,
            "model_family": model["metadata"]["family"],
            "framework": model["framework"],
            "file": "model",
            "metadata": model["metadata"],
        },
    }
    _env(monkeypatch, tmp_path / "input2", out2, "inference", model_dir=out1)
    (tmp_path / "input2").mkdir()
    backend2 = FakeBackend(spec2)
    assert runtime.run(backend2) == 0
    result, output_path = backend2.result_
    assert output_path == "output/predictions.csv" and (out2 / "output" / "predictions.csv").exists()
    assert [r["prediction"] for r in result["preview"]] == ["pass", "fail"]
    assert backend2.artifacts_[0]["kind"] == "report"


def test_failure_reports_status(tmp_path, monkeypatch):
    input_dir, out = tmp_path / "input", tmp_path / "out"
    input_dir.mkdir()
    spec = {
        "job_id": 7,
        "kind": "train",
        "project_slug": "demo",
        "data_type": "TABULAR",
        "task_type": "classification",
        "mode": "manual",
        "model_family": "tabular.linear",
        "config": {},
        "input": {"kind": "upload", "format": "csv", "spec": {"target": "label"}},
        "artifact": None,
        "resources": {"gpu": 0, "cpu": 1, "memory_mb": 512},
        "timeout_minutes": 10,
        "families": families_for_spec("tabular.linear"),
        "zoo_weights": {},
    }
    _env(monkeypatch, input_dir, out, "train")
    backend = FakeBackend(spec)
    assert runtime.run(backend) == 1  # no csv in the input dir
    assert backend.statuses[-1]["status"] == "failed" and "FileNotFoundError" in backend.statuses[-1]["message"]
