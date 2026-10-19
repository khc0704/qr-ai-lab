"""YOLO on CPU with a tiny synthetic dataset: from-scratch (architecture yaml, no download) and, when
QR_TEST_ZOO points at a zoo folder holding yolov8n.pt, fine-tuning from the pretrained checkpoint."""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("torch")
pytest.importorskip("ultralytics")

from trainer.dataset import Dataset
from trainer.models import registry
from trainer.models.zoo import resolver


def _det_dataset(root: Path, n_train: int = 24, n_val: int = 8, size: int = 96) -> Path:
    from PIL import Image

    rng = np.random.default_rng(0)
    for split, n in (("train", n_train), ("val", n_val)):
        (root / "images" / split).mkdir(parents=True, exist_ok=True)
        (root / "labels" / split).mkdir(parents=True, exist_ok=True)
        for i in range(n):
            img = rng.integers(80, 120, size=(size, size), dtype=np.uint8)
            cls = int(rng.integers(0, 2))
            w, h = int(rng.integers(16, 30)), int(rng.integers(16, 30))
            x, y = int(rng.integers(0, size - w)), int(rng.integers(0, size - h))
            img[y : y + h, x : x + w] = 250 if cls == 0 else 10
            Image.fromarray(img, mode="L").convert("RGB").save(root / "images" / split / f"{split}_{i}.png")
            cx, cy = (x + w / 2) / size, (y + h / 2) / size
            (root / "labels" / split / f"{split}_{i}.txt").write_text(
                f"{cls} {cx:.4f} {cy:.4f} {w / size:.4f} {h / size:.4f}\n"
            )
    yaml_path = root / "data.yaml"
    yaml_path.write_text(f"path: {root}\ntrain: images/train\nval: images/val\nnames:\n  0: spot\n  1: hole\n")
    return yaml_path


def _cls_dataset(root: Path, per_class: int = 10, size: int = 64) -> tuple[list[Path], list[str]]:
    from PIL import Image

    rng = np.random.default_rng(1)
    paths, labels = [], []
    for cls, (lo, hi) in {"bright": (170, 250), "dark": (5, 80)}.items():
        (root / cls).mkdir(parents=True, exist_ok=True)
        for i in range(per_class):
            a = rng.integers(lo, hi, size=(size, size), dtype=np.uint8)
            p = root / cls / f"{cls}_{i}.png"
            Image.fromarray(a, mode="L").convert("RGB").save(p)
            paths.append(p)
            labels.append(cls)
    return paths, labels


def _params(pretrained: bool) -> dict:
    return {"model": "yolov8n", "epochs": 2, "imgsz": 96, "batch": 8, "lr0": 0.01, "pretrained": pretrained}


def test_yolo_detection_from_scratch_cpu(tmp_path, ctx):
    data_yaml = _det_dataset(tmp_path / "det")
    ds = Dataset(
        "IMAGE",
        "detection",
        {},
        X=sorted((tmp_path / "det" / "images").rglob("*.png")),
        root=tmp_path / "det",
        data_yaml=data_yaml,
    )
    ds.ids = [p.name for p in ds.X]
    t = registry.create_trainer("vision.yolo", "detection", _params(pretrained=False), ctx)
    t.fit(ds)
    m = t.evaluate()
    assert "map50_95" in m and t.best_pt is not None and t.best_pt.exists()
    arts = t.export(tmp_path / "out")
    assert (tmp_path / "out" / "model" / "best.pt").exists() and arts[0].metadata["classes"] == ["spot", "hole"]
    inf = registry.create_inferencer("vision.yolo", ctx)
    inf.load(tmp_path / "out" / "model", arts[0].metadata)
    probe = Dataset("IMAGE", "detection", {}, X=ds.X[:3], ids=["a", "b", "c"], root=ds.root)
    res = inf.predict(probe, "detect", {"conf": 0.01, "save_images": False}, tmp_path / "pred")
    assert res.summary["images"] == 3 and "class_counts" in res.summary
    assert (tmp_path / "pred" / "detections.jsonl").exists()


def test_yolo_classification_from_scratch_cpu(tmp_path, ctx):
    paths, labels = _cls_dataset(tmp_path / "cls")
    ds = Dataset(
        "IMAGE",
        "classification",
        {},
        X=paths,
        y=labels,
        ids=[p.name for p in paths],
        root=tmp_path / "cls",
        classes=["bright", "dark"],
    )
    t = registry.create_trainer("vision.yolo", "classification", {**_params(pretrained=False), "imgsz": 64}, ctx)
    t.fit(ds)
    m = t.evaluate()
    assert "accuracy" in m and "f1_macro" in m
    arts = t.export(tmp_path / "out")
    inf = registry.create_inferencer("vision.yolo", ctx)
    inf.load(tmp_path / "out" / "model", arts[0].metadata)
    res = inf.predict(
        Dataset("IMAGE", "classification", {}, X=paths[:2] + paths[-2:], ids=list("abcd"), root=tmp_path / "cls"),
        "predict",
        {},
        tmp_path / "pred",
    )
    assert len(res.rows) == 4 and {r["prediction"] for r in res.rows} <= {"bright", "dark"} and "top5" in res.rows[0]


@pytest.mark.skipif(not os.environ.get("QR_TEST_ZOO"), reason="QR_TEST_ZOO not set (needs yolov8n.pt)")
def test_yolo_finetune_from_zoo_cpu(tmp_path, ctx):
    zoo = Path(os.environ["QR_TEST_ZOO"])
    ctx.zoo = resolver(zoo, {"yolov8n": "yolov8n.pt"})
    data_yaml = _det_dataset(tmp_path / "det", n_train=16, n_val=8)
    ds = Dataset(
        "IMAGE",
        "detection",
        {},
        X=sorted((tmp_path / "det" / "images").rglob("*.png")),
        root=tmp_path / "det",
        data_yaml=data_yaml,
    )
    t = registry.create_trainer("vision.yolo", "detection", {**_params(pretrained=True), "epochs": 1}, ctx)
    t.fit(ds)
    assert "map50_95" in t.evaluate() and t.best_pt.exists()


def test_missing_zoo_weight_fails_clearly(tmp_path, ctx):
    ctx.zoo = resolver(tmp_path / "empty-zoo", {"yolov8n": "yolov8n.pt"})
    (tmp_path / "empty-zoo").mkdir()
    t = registry.create_trainer("vision.yolo", "detection", _params(pretrained=True), ctx)
    data_yaml = _det_dataset(tmp_path / "det", n_train=2, n_val=2)
    ds = Dataset("IMAGE", "detection", {}, X=[], root=tmp_path / "det", data_yaml=data_yaml)
    with pytest.raises(FileNotFoundError, match="模型庫缺少權重"):
        t.fit(ds)
