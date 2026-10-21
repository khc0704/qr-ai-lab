"""AutoML guards: label-dependent metric without labels fails fast; the job deadline stops a trial and the
best-so-far model is exported; a cancel after one finished trial still registers that model."""

from __future__ import annotations

import json

import pytest

from tests import fake_family
from tests.conftest import anomaly_frame, cls_frame, families_for_spec
from tests.test_runtime import FakeBackend, _env
from trainer import runtime
from trainer.models import registry
from trainer.models.base import Context, TrialTimeout


@pytest.fixture
def fake_registry(monkeypatch):
    monkeypatch.setitem(registry.FAMILIES, fake_family.FAMILY, ("tests.fake_family", "FakeTrainer", "FakeInferencer"))
    fake_family.reset()
    yield
    fake_family.reset()


def _spec(tmp_path, *, timeout_minutes: int = 10, max_trials: int = 3, budget_minutes: float = 5) -> dict:
    input_dir = tmp_path / "input"
    input_dir.mkdir(exist_ok=True)
    cls_frame().to_csv(input_dir / "train.csv", index=False)
    return {
        "job_id": 7,
        "kind": "train",
        "project_slug": "demo",
        "data_type": "TABULAR",
        "task_type": "classification",
        "mode": "auto",
        "model_family": None,
        "config": {
            "search": {
                "candidates": [fake_family.FAMILY],
                "metric": "f1_macro",
                "direction": "maximize",
                "max_trials": max_trials,
                "time_budget_minutes": budget_minutes,
            },
            "epochs": 4,
            "sleep": 0.3,
        },
        "input": {"kind": "upload", "format": "csv", "spec": {"target": "label"}},
        "artifact": None,
        "resources": {"gpu": 0, "cpu": 1.5, "memory_mb": 1024},
        "timeout_minutes": timeout_minutes,
        "families": {fake_family.FAMILY: {"defaults": {}, "search_space": {}}},
        "zoo_weights": {},
    }


def test_context_deadline_raises_trial_timeout():
    ctx = Context(work_dir=None, deadline=-1.0)  # already in the past
    with pytest.raises(TrialTimeout):
        ctx.epoch(1, {"f1_macro": 0.5})
    with pytest.raises(TrialTimeout):
        ctx.progress(0.5)
    ctx.deadline = None
    ctx.progress(0.5)  # no deadline → nothing raised


def test_deadline_mid_trial_exports_best_so_far(tmp_path, monkeypatch, fake_registry):
    # 0.85 × timeout ≈ 1.5 s: trial 1 finishes instantly, trial 2 sleeps 0.5 s per epoch (4 epochs) and runs
    # into the deadline mid-trial
    fake_family.reset(slow_from_fit=2)
    spec = _spec(tmp_path, max_trials=5)
    spec["config"]["sleep"] = 0.5
    spec["timeout_minutes"] = 0.03
    _env(monkeypatch, tmp_path / "input", tmp_path / "out", "train")
    backend = FakeBackend(spec)
    assert runtime.run(backend) == 0, backend.statuses[-1]
    result = backend.result_[0]
    assert result["stopped"] == "deadline" and result["n_trials"] == 1 and result["model_family"] == fake_family.FAMILY
    model = next(a for a in backend.artifacts_ if a["kind"] == "model")
    assert json.loads((tmp_path / "out" / "model" / "model.json").read_text())["fit"] == 1
    assert model["retry"] == "long" and backend.statuses[-1]["status"] == "succeeded"
    assert json.loads((tmp_path / "out" / "metrics" / "metrics.json").read_text())["stopped"] == "deadline"


def test_cancel_after_a_finished_trial_registers_best_so_far(tmp_path, monkeypatch, fake_registry):
    fake_family.reset(cancel_on_fit=2)
    spec = _spec(tmp_path, max_trials=3)
    _env(monkeypatch, tmp_path / "input", tmp_path / "out", "train")
    backend = FakeBackend(spec)
    assert runtime.run(backend) == 143  # still a cancelled job …
    assert backend.statuses[-1]["stage"] == "cancelled" and backend.statuses[-1]["retry"] == "none"
    model = next(a for a in backend.artifacts_ if a["kind"] == "model")  # … but the best model is registered
    assert model["retry"] == "none" and model["metadata"]["family"] == fake_family.FAMILY
    assert backend.result_[0]["stopped"] == "cancelled" and backend.result_[0]["n_trials"] == 1


def test_cancel_before_any_trial_exports_nothing(tmp_path, monkeypatch, fake_registry):
    fake_family.reset(cancel_on_fit=1)
    spec = _spec(tmp_path)
    _env(monkeypatch, tmp_path / "input", tmp_path / "out", "train")
    backend = FakeBackend(spec)
    assert runtime.run(backend) == 143 and backend.artifacts_ == [] and backend.result_ is None


def test_unlabeled_anomaly_detection_fails_before_first_trial(tmp_path, monkeypatch):
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    anomaly_frame().drop(columns=["is_anomaly"]).to_csv(input_dir / "fdc.csv", index=False)
    spec = {
        **_spec(tmp_path),
        "task_type": "anomaly_detection",
        "config": {
            "search": {
                "candidates": ["tabular.isolation_forest"],
                "metric": "auroc",
                "direction": "maximize",
                "max_trials": 3,
                "time_budget_minutes": 5,
            }
        },
        "input": {"kind": "upload", "format": "csv", "spec": {}},
        "families": families_for_spec("tabular.isolation_forest"),
    }
    (input_dir / "train.csv").unlink()
    _env(monkeypatch, input_dir, tmp_path / "out", "train")
    backend = FakeBackend(spec)
    assert runtime.run(backend) == 1
    msg = backend.statuses[-1]["message"]
    assert "auroc" in msg and "標籤" in msg and "手動模式" in msg
    assert backend.metrics_ == [] and backend.artifacts_ == []  # nothing was trained


def test_labeled_anomaly_detection_runs_automl(tmp_path, monkeypatch):
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    anomaly_frame().to_csv(input_dir / "fdc.csv", index=False)
    spec = {
        **_spec(tmp_path),
        "task_type": "anomaly_detection",
        "config": {
            "search": {
                "candidates": ["tabular.isolation_forest"],
                "metric": "auroc",
                "direction": "maximize",
                "max_trials": 2,
                "time_budget_minutes": 5,
            },
            "n_estimators": 50,
        },
        "input": {"kind": "upload", "format": "csv", "spec": {"target": "is_anomaly"}},
        "families": families_for_spec("tabular.isolation_forest"),
    }
    (input_dir / "train.csv").unlink()
    _env(monkeypatch, input_dir, tmp_path / "out", "train")
    backend = FakeBackend(spec)
    assert runtime.run(backend) == 0, backend.statuses[-1]
    assert backend.result_[0]["n_trials"] == 2 and backend.result_[0]["metrics"]["auroc"] > 0.9


def test_cpu_grant_is_rounded_up(tmp_path, monkeypatch, fake_registry):
    seen: list[int] = []
    original = registry.create_trainer

    def spy(fid, task, params, ctx):
        seen.append(ctx.cpu)
        return original(fid, task, params, ctx)

    monkeypatch.setattr(registry, "create_trainer", spy)
    spec = _spec(tmp_path, max_trials=1)
    _env(monkeypatch, tmp_path / "input", tmp_path / "out", "train")
    assert runtime.run(FakeBackend(spec)) == 0
    assert seen == [2]  # resources.cpu = 1.5 → ceil → 2 (the runner pins ceil(cpu) cores)


def test_automl_only_samples_choices_whose_weights_exist(tmp_path):
    from trainer.automl import available_choices, weight_id
    from trainer.models.base import Context
    from trainer.models.zoo import resolver

    zoo = tmp_path / "zoo"
    (zoo / "dinov2-small").mkdir(parents=True)
    (zoo / "yolov8n-cls.pt").write_bytes(b"")
    files = {
        "dinov2-small": "dinov2-small/",
        "dinov3-vits16": "dinov3-vits16/",
        "yolov8n-cls": "yolov8n-cls.pt",
        "yolov8m-cls": "yolov8m-cls.pt",
    }
    ctx = Context(work_dir=tmp_path, zoo=resolver(zoo, files))
    assert weight_id("vision.yolo", "classification", "model", "yolov8m") == "yolov8m-cls"
    assert weight_id("vision.dino", "classification", "backbone", "dinov3-vits16") == "dinov3-vits16"
    assert weight_id("vision.yolo", "detection", "imgsz", 640) is None
    dino = ["dinov2-small", "dinov3-vits16"]
    assert available_choices(ctx, "vision.dino", "classification", "backbone", dino) == ["dinov2-small"]
    yolo = ["yolov8n", "yolov8s", "yolov8m"]
    assert available_choices(ctx, "vision.yolo", "classification", "model", yolo) == ["yolov8n"]
    assert available_choices(ctx, "vision.yolo", "classification", "imgsz", [512, 640]) == [512, 640]
    # nothing present → keep the list so the trial reports the missing weight itself
    assert available_choices(ctx, "vision.dino", "classification", "backbone", ["dinov3-vitb16"]) == ["dinov3-vitb16"]
    assert available_choices(Context(work_dir=tmp_path), "vision.yolo", "detection", "model", ["yolov8n"]) == [
        "yolov8n"
    ]
