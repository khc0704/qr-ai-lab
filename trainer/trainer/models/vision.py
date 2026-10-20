"""Vision families: YOLO (ultralytics), DINOv2 few-shot prototypes, DINOv2 PatchCore anomaly detection.

Weights never come from the network: YOLO checkpoints and DINOv2 folders are resolved through ctx.weight()
(the model zoo). `pretrained: false` builds YOLO from its architecture yaml (bundled with ultralytics).
"""

from __future__ import annotations

import json
import os
import re
import shutil
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any

import numpy as np

from trainer import jsonsafe
from trainer import metrics as M
from trainer.data.image import all_images, class_folders
from trainer.data.split import holdout
from trainer.dataset import Dataset
from trainer.log import info, warn
from trainer.models.base import ArtifactOut, BaseInferencer, BaseTrainer, PredictResult
from trainer.models.tabular import _binary_anomaly_labels

# ---------------------------------------------------------------------------------------------------
# YOLO
# ---------------------------------------------------------------------------------------------------

YOLO_SUFFIX = {"detection": "", "segmentation": "-seg", "classification": "-cls"}
YOLO_DEFAULT_MODEL = "yolov8s"  # ultralytics 8.1.x ships YOLOv8 only (YOLO11 needs 8.3+)


def _ultralytics_yolo():
    """Import YOLO after preparing the process for ultralytics 8.1 on a modern torch.

    ultralytics 8.1 calls torch.load() without `weights_only`; torch >= 2.6 defaults that to True and refuses
    its own checkpoints (they pickle ultralytics model classes). TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD only changes
    the default for callers that do not pass `weights_only`, so the trainer's explicit weights_only=True loads
    stay strict. YOLO checkpoints only come from the admin-managed model zoo or this job's own training run.
    """
    import warnings

    os.environ.setdefault("TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD", "1")
    warnings.filterwarnings("ignore", message=".*TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD.*")
    from ultralytics import YOLO

    return YOLO


def _yolo_device(ctx) -> str | int:
    return 0 if ctx.device == "cuda" else "cpu"


def _prepare_cls_folder(ds: Dataset, work_dir: Path) -> Path:
    """ultralytics classification wants root/{train,val}/<class>/; build it with symlinks if missing."""
    root = ds.root
    assert root is not None
    if (root / "train").is_dir() and any((root / s).is_dir() for s in ("val", "valid", "test")):
        return root
    target = work_dir / "cls"
    labels = np.asarray(ds.y)
    tr, va = holdout(len(ds), labels, "classification")
    for split, idx in (("train", tr), ("val", va)):
        for i in idx:
            dst = target / split / str(labels[i]) / Path(ds.X[i]).name
            dst.parent.mkdir(parents=True, exist_ok=True)
            if not dst.exists():
                try:
                    os.symlink(ds.X[i], dst)
                except OSError:
                    shutil.copy2(ds.X[i], dst)
    return target


class YoloTrainer(BaseTrainer):
    framework = "ultralytics"

    def __init__(self, family: str, task: str | None, params: dict[str, Any], ctx) -> None:
        super().__init__(family, task, params, ctx)
        self.inference_modes = {
            "detection": ["detect"],
            "segmentation": ["segment", "measure"],
            "classification": ["predict"],
        }.get(task or "", ["detect"])
        self.best_pt: Path | None = None
        self.names: dict[int, str] = {}
        self.results_csv: Path | None = None

    def _weights(self):
        YOLO = _ultralytics_yolo()

        model_id = str(self.params.get("model", YOLO_DEFAULT_MODEL))
        suffix = YOLO_SUFFIX.get(self.task or "detection", "")
        if self.params.get("pretrained", True):
            path = self.ctx.weight(f"{model_id}{suffix}")
            info(f"yolo: pretrained weights {path.name} from the model zoo")
            return YOLO(str(path))
        info(f"yolo: from scratch ({model_id}{suffix}.yaml)")
        return YOLO(f"{model_id}{suffix}.yaml")

    def fit(self, ds: Dataset) -> None:
        if self.task in ("detection", "segmentation"):
            if ds.data_yaml is None:
                raise ValueError("偵測 / 分割需要 YOLO 格式資料集（含 data.yaml、images/、labels/）")
            data = str(ds.data_yaml)
        else:
            if not ds.has_labels:
                raise ValueError("分類需要以類別命名的資料夾（<class>/*.jpg）")
            data = str(_prepare_cls_folder(ds, self.ctx.work_dir))
        model = self._weights()
        epochs = int(self.params.get("epochs", 100))
        ctx = self.ctx

        def on_epoch_end(trainer) -> None:
            m = {k.split("/")[-1]: float(v) for k, v in (trainer.metrics or {}).items()}
            mapped = _map_yolo_metrics(m, self.task)
            e = int(trainer.epoch) + 1
            info(f"epoch {e}/{epochs} " + " ".join(f"{k}={v:.4f}" for k, v in (mapped or m).items()))
            ctx.epoch(e, mapped)
            ctx.progress(e / epochs, "training")

        model.add_callback("on_fit_epoch_end", on_epoch_end)
        kwargs: dict[str, Any] = {
            "data": data,
            "epochs": epochs,
            "imgsz": int(self.params.get("imgsz", 640 if self.task != "classification" else 224)),
            "lr0": float(self.params.get("lr0", 0.01)),
            "batch": int(self.params.get("batch", -1))
            if self.task != "classification"
            else int(self.params.get("batch", 32) if int(self.params.get("batch", 32)) > 0 else 32),
            "device": _yolo_device(ctx),
            "workers": ctx.workers,
            "project": str(ctx.work_dir / "yolo"),
            "name": "run",
            "exist_ok": True,
            "pretrained": bool(self.params.get("pretrained", True)),
            "plots": False,
            "verbose": False,  # per-epoch lines come from on_epoch_end; YOLO_VERBOSE=false silences its bars
            "seed": int(self.params.get("seed", 42)),
            # AMP off unless asked (config `amp: true`): ultralytics' AMP check wants to download a checkpoint
            "amp": bool(self.params.get("amp", False)) and ctx.device == "cuda",
        }
        try:
            results = model.train(**kwargs)
        except RuntimeError as e:
            if "out of memory" in str(e).lower() and kwargs["batch"] not in (-1, 1):
                warn("yolo: CUDA out of memory → retrying with half batch")
                kwargs["batch"] = max(1, kwargs["batch"] // 2)
                results = model.train(**kwargs)
            else:
                raise
        self.best_pt = Path(model.trainer.best)
        self.results_csv = Path(model.trainer.save_dir) / "results.csv"
        self.names = dict(model.names)
        raw = (
            {k.split("/")[-1]: float(v) for k, v in getattr(results, "results_dict", {}).items()}
            if results is not None
            else {}
        )
        self.metrics = _map_yolo_metrics(raw, self.task)
        if self.task == "classification":
            self.metrics.update(self._cls_f1(Path(data)))
        self.meta.update(
            {
                "classes": [self.names[k] for k in sorted(self.names)],
                "imgsz": kwargs["imgsz"],
                "model": self.params.get("model"),
            }
        )
        info(f"{self.family}: " + ", ".join(f"{k}={v:.4f}" for k, v in self.metrics.items()))

    def _cls_f1(self, root: Path) -> dict[str, float]:
        YOLO = _ultralytics_yolo()

        val_dir = next((root / s for s in ("val", "valid", "test") if (root / s).is_dir()), None)
        if val_dir is None or self.best_pt is None:
            return {}
        folders = class_folders(val_dir)
        paths = [p for v in folders.values() for p in v]
        truth = [k for k, v in folders.items() for _ in v]
        model = YOLO(str(self.best_pt))
        preds = []
        for r in model.predict(
            paths,
            imgsz=self.meta.get("imgsz", 224),
            device=_yolo_device(self.ctx),
            verbose=False,
            stream=True,
        ):
            preds.append(model.names[int(r.probs.top1)])
        return {k: v for k, v in M.classification(truth, preds).items() if k in ("f1_macro", "accuracy")}

    def export(self, out: Path) -> list[ArtifactOut]:
        assert self.best_pt is not None
        model_dir = out / "model"
        model_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(self.best_pt, model_dir / "best.pt")
        meta = {
            "classes": self.meta.get("classes"),
            "imgsz": self.meta.get("imgsz"),
            "metrics": self.metrics,
        }
        (model_dir / "metadata.json").write_text(jsonsafe.dumps(meta, indent=2), encoding="utf-8")
        arts = [
            ArtifactOut(
                name="yolo",
                kind="model",
                path="model",
                framework=self.framework,
                metrics=self.metrics,
                metadata=meta,
            )
        ]
        if self.results_csv and self.results_csv.exists():
            rep = out / "report"
            rep.mkdir(parents=True, exist_ok=True)
            shutil.copy2(self.results_csv, rep / "training_curve.csv")
            arts.append(
                ArtifactOut(
                    name="training_curve",
                    kind="report",
                    path="report/training_curve.csv",
                    framework=self.framework,
                )
            )
        return arts


def _map_yolo_metrics(m: dict[str, float], task: str | None) -> dict[str, float]:
    out: dict[str, float] = {}
    if task == "classification":
        if "accuracy_top1" in m:
            out["accuracy"] = m["accuracy_top1"]
        if "accuracy_top5" in m:
            out["accuracy_top5"] = m["accuracy_top5"]
        return out
    if "mAP50-95(B)" in m:
        out["map50_95"] = m["mAP50-95(B)"]
        out["map50"] = m.get("mAP50(B)", 0.0)
    if task == "segmentation" and "mAP50-95(M)" in m:
        out["mask_map50_95"] = m["mAP50-95(M)"]
        out["mask_map50"] = m.get("mAP50(M)", 0.0)
    for k in ("precision(B)", "recall(B)"):
        if k in m:
            out[k.split("(")[0]] = m[k]
    return out


class YoloInferencer(BaseInferencer):
    def load(self, model_path: Path, metadata: dict[str, Any]) -> None:
        YOLO = _ultralytics_yolo()

        self.model = YOLO(str(model_path / "best.pt"))
        self.meta = metadata or {}
        self.imgsz = int(self.meta.get("imgsz") or 640)

    def predict(self, ds: Dataset, mode: str, options: dict[str, Any], out: Path) -> PredictResult:
        out.mkdir(parents=True, exist_ok=True)
        paths = [str(p) for p in ds.X]
        ids = ds.ids or [Path(p).name for p in paths]
        save = bool(options.get("save_images", True))
        rows: list[dict[str, Any]] = []
        per_image: list[dict[str, Any]] = []
        pixel = options.get("pixel_size")  # physical size of one pixel (e.g. nm); measurements are scaled by it
        counts: Counter[str] = Counter()
        results = self.model.predict(
            paths,
            imgsz=int(options.get("imgsz") or self.imgsz),
            conf=float(options.get("conf", 0.25)),
            device=_yolo_device(self.ctx),
            stream=True,
            verbose=False,
            save=save,
            project=str(out),
            name="images",
            exist_ok=True,
        )
        for k, r in enumerate(results):
            self.ctx.progress((k + 1) / max(1, len(paths)))
            image_id = ids[k]
            if mode == "predict" or (getattr(r, "probs", None) is not None and r.boxes is None):
                top = int(r.probs.top1)
                label = self.model.names[top]
                counts[label] += 1
                rows.append(
                    {
                        "id": image_id,
                        "prediction": label,
                        "confidence": float(r.probs.top1conf),
                        "top5": [self.model.names[int(i)] for i in r.probs.top5],
                    }
                )
                continue
            boxes = r.boxes
            n = 0 if boxes is None else len(boxes)
            objs = []
            for j in range(n):
                cls = self.model.names[int(boxes.cls[j])]
                counts[cls] += 1
                x1, y1, x2, y2 = (float(v) for v in boxes.xyxy[j].tolist())
                row: dict[str, Any] = {
                    "id": image_id,
                    "object": j,
                    "class": cls,
                    "confidence": float(boxes.conf[j]),
                    "x1": x1,
                    "y1": y1,
                    "x2": x2,
                    "y2": y2,
                }
                if mode in ("segment", "measure") and r.masks is not None:
                    mask = r.masks.data[j].cpu().numpy() > 0.5
                    area = float(mask.sum())
                    scale_y = r.orig_shape[0] / mask.shape[0]
                    scale_x = r.orig_shape[1] / mask.shape[1]
                    area_px = area * scale_x * scale_y
                    row.update(
                        {
                            "area_px": area_px,
                            "width_px": x2 - x1,
                            "height_px": y2 - y1,
                            "equiv_diameter_px": float(2 * np.sqrt(area_px / np.pi)),
                        }
                    )
                    if pixel:
                        s = float(pixel)
                        row.update(
                            {
                                "area_phys": area_px * s * s,
                                "width_phys": (x2 - x1) * s,
                                "height_phys": (y2 - y1) * s,
                                "equiv_diameter_phys": row["equiv_diameter_px"] * s,
                            }
                        )
                rows.append(row)
                objs.append(row)
            per_image.append({"id": image_id, "n_objects": n, "objects": objs})
        (out / "detections.jsonl").write_text("\n".join(jsonsafe.dumps(x) for x in per_image), encoding="utf-8")
        extra = (
            [
                ArtifactOut(
                    name="detections",
                    kind="report",
                    path="output/detections.jsonl",
                    framework="ultralytics",
                )
            ]
            if per_image
            else []
        )
        if save and (out / "images").exists():
            extra.append(
                ArtifactOut(
                    name="annotated_images",
                    kind="report",
                    path="output/images",
                    framework="ultralytics",
                )
            )
        summary: dict[str, Any] = {"mode": mode, "images": len(paths), "class_counts": dict(counts)}
        if per_image:
            summary["total_objects"] = int(sum(x["n_objects"] for x in per_image))
            summary["images_without_objects"] = int(sum(1 for x in per_image if x["n_objects"] == 0))
        return PredictResult(rows, summary, extra)


# ---------------------------------------------------------------------------------------------------
# DINOv2 (frozen backbone) — few-shot prototypes and PatchCore
# ---------------------------------------------------------------------------------------------------


class _Dino:
    """Frozen DINOv2 from the zoo; returns CLS (+ mean patch) embeddings and patch token grids."""

    def __init__(self, ctx, backbone_id: str) -> None:
        import torch
        from transformers import AutoImageProcessor, AutoModel

        path = ctx.weight(backbone_id)
        self.ctx = ctx
        self.processor = AutoImageProcessor.from_pretrained(str(path), local_files_only=True)
        self.model = AutoModel.from_pretrained(str(path), local_files_only=True).to(ctx.device).eval()
        self.torch = torch
        self.backbone_id = backbone_id
        info(f"dino: loaded {backbone_id} from {path} on {ctx.device}")

    def _batches(self, paths: list[Path], batch: int):
        from PIL import Image

        for s in range(0, len(paths), batch):
            imgs = [Image.open(p).convert("RGB") for p in paths[s : s + batch]]
            yield self.processor(images=imgs, return_tensors="pt")["pixel_values"].to(self.ctx.device)

    def embed(self, paths: list[Path], *, patches: bool = False, batch: int = 16, progress=None):
        torch = self.torch
        cls_out, patch_out = [], []
        with torch.no_grad():
            for k, px in enumerate(self._batches(paths, batch)):
                h = self.model(pixel_values=px).last_hidden_state  # (B, 1 + L, D)
                cls = torch.cat([h[:, 0], h[:, 1:].mean(dim=1)], dim=1)
                cls_out.append(torch.nn.functional.normalize(cls, dim=1).cpu().numpy())
                if patches:
                    patch_out.append(torch.nn.functional.normalize(h[:, 1:], dim=-1).cpu().numpy().astype(np.float16))
                if progress:
                    progress(min(1.0, (k + 1) * batch / max(1, len(paths))))
        cls_arr = np.concatenate(cls_out) if cls_out else np.zeros((0, 1), np.float32)
        return (cls_arr, np.concatenate(patch_out) if patch_out else None) if patches else cls_arr


def _prototypes(emb: np.ndarray, labels: np.ndarray) -> tuple[list[str], np.ndarray]:
    classes = sorted(set(labels.tolist()))
    protos = np.stack([emb[labels == c].mean(axis=0) for c in classes])
    protos /= np.linalg.norm(protos, axis=1, keepdims=True) + 1e-9
    return classes, protos


def _nearest(
    emb: np.ndarray,
    classes: list[str],
    protos: np.ndarray,
    support: np.ndarray | None,
    support_labels: np.ndarray | None,
    k: int,
):
    sims = emb @ protos.T
    pred_idx = sims.argmax(axis=1)
    preds = [classes[i] for i in pred_idx]
    conf = sims.max(axis=1)
    if support is not None and support_labels is not None and k > 1 and len(support) >= k:
        ssims = emb @ support.T
        knn = np.argsort(-ssims, axis=1)[:, :k]
        votes = []
        for n in range(len(emb)):
            c = Counter(support_labels[knn[n]].tolist())
            top = c.most_common(1)[0]
            votes.append(top[0] if top[1] > k / 2 else preds[n])
        preds = votes
    return preds, conf, sims


class DinoFewShotTrainer(BaseTrainer):
    framework = "torch"
    inference_modes = ["predict", "embed", "retrieve", "extend"]

    def fit(self, ds: Dataset) -> None:
        if not ds.has_labels:
            raise ValueError("few-shot 分類需要以類別（bin code）命名的資料夾")
        self.backbone_id = str(self.params.get("backbone", "dinov2-small"))
        self.k = int(self.params.get("k", 5))
        dino = _Dino(self.ctx, self.backbone_id)
        labels = np.asarray(ds.y).astype(str)
        self.ctx.progress(0.05, "training")
        emb = dino.embed(list(ds.X), progress=lambda f: self.ctx.progress(0.05 + 0.8 * f, "training"))
        self.emb, self.labels, self.ids = emb, labels, np.asarray(ds.ids)
        counts = Counter(labels.tolist())
        if min(counts.values()) >= 2 and len(counts) >= 2:
            tr, va = holdout(len(labels), labels, "classification")
            classes, protos = _prototypes(emb[tr], labels[tr])
            preds, _, _ = _nearest(emb[va], classes, protos, emb[tr], labels[tr], self.k)
            self.metrics = M.classification(labels[va], preds)
        else:  # leave-one-out nearest prototype
            preds = []
            for n in range(len(labels)):
                keep = np.arange(len(labels)) != n
                classes, protos = _prototypes(emb[keep], labels[keep])
                preds.append(_nearest(emb[n : n + 1], classes, protos, None, None, 1)[0][0])
            self.metrics = M.classification(labels, preds)
        self.classes, self.protos = _prototypes(emb, labels)
        self.meta.update(
            {
                "classes": self.classes,
                "backbone": self.backbone_id,
                "k": self.k,
                "support_per_class": dict(counts),
            }
        )
        info(
            f"{self.family}: classes={len(self.classes)} support={len(labels)} "
            + ", ".join(f"{k}={v:.4f}" for k, v in self.metrics.items())
        )

    def export(self, out: Path) -> list[ArtifactOut]:
        return [
            _save_bank(
                out,
                self.classes,
                self.protos,
                self.emb,
                self.labels,
                self.ids,
                self.meta,
                self.metrics,
            )
        ]


def _save_bank(
    out: Path,
    classes,
    protos,
    emb,
    labels,
    ids,
    meta: dict[str, Any],
    metrics: dict[str, float],
    *,
    set_default: bool = False,
) -> ArtifactOut:
    model_dir = out / "model"
    model_dir.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        model_dir / "prototypes.npz",
        classes=np.asarray(classes, dtype=str),
        prototypes=protos.astype(np.float32),
        support=emb.astype(np.float32),
        support_labels=np.asarray(labels, dtype=str),
        support_ids=np.asarray(ids, dtype=str),
    )
    full_meta = {
        **meta,
        "classes": list(classes),
        "metrics": metrics,
        "inference_modes": DinoFewShotTrainer.inference_modes,
    }
    (model_dir / "metadata.json").write_text(jsonsafe.dumps(full_meta, indent=2), encoding="utf-8")
    return ArtifactOut(
        name="dino_fewshot",
        kind="model",
        path="model",
        framework="torch",
        metrics=metrics,
        metadata=full_meta,
        set_default=set_default,
    )


class DinoFewShotInferencer(BaseInferencer):
    def load(self, model_path: Path, metadata: dict[str, Any]) -> None:
        bank = np.load(model_path / "prototypes.npz", allow_pickle=False)
        self.classes = bank["classes"].astype(str).tolist()
        self.protos = bank["prototypes"]
        self.support = bank["support"]
        self.support_labels = bank["support_labels"].astype(str)
        self.support_ids = bank["support_ids"].astype(str)
        local = model_path / "metadata.json"
        self.meta = {
            **(json.loads(local.read_text(encoding="utf-8")) if local.exists() else {}),
            **(metadata or {}),
        }
        self.dino = _Dino(self.ctx, str(self.meta.get("backbone", "dinov2-small")))

    def predict(self, ds: Dataset, mode: str, options: dict[str, Any], out: Path) -> PredictResult:
        out.mkdir(parents=True, exist_ok=True)
        ids = ds.ids or [Path(p).name for p in ds.X]
        emb = self.dino.embed(list(ds.X), progress=lambda f: self.ctx.progress(0.8 * f))
        k = int(options.get("k", self.meta.get("k", 5)))
        if mode == "extend":
            return self._extend(ds, emb, out)
        if mode == "embed":
            np.save(out / "embeddings.npy", emb)
            rows = [{"id": i, "embedding": [round(float(v), 6) for v in e]} for i, e in zip(ids, emb, strict=True)]
            return PredictResult(
                rows,
                {"mode": mode, "n": len(rows), "dim": int(emb.shape[1])},
                [
                    ArtifactOut(
                        name="embeddings",
                        kind="report",
                        path="output/embeddings.npy",
                        framework="torch",
                    )
                ],
            )
        if mode == "retrieve":
            sims = emb @ self.support.T
            rows = []
            for n, i in enumerate(ids):
                order = np.argsort(-sims[n])
                rows.append(
                    {
                        "id": i,
                        "max_similarity": float(sims[n][order[0]]),
                        "most_similar": [
                            {
                                "id": str(self.support_ids[j]),
                                "label": str(self.support_labels[j]),
                                "similarity": round(float(sims[n][j]), 5),
                            }
                            for j in order[:k]
                        ],
                        "least_similar": [
                            {
                                "id": str(self.support_ids[j]),
                                "label": str(self.support_labels[j]),
                                "similarity": round(float(sims[n][j]), 5),
                            }
                            for j in order[::-1][:k]
                        ],
                    }
                )
            novel = sorted(rows, key=lambda r: r["max_similarity"])[:20]
            return PredictResult(
                rows,
                {
                    "mode": mode,
                    "n": len(rows),
                    "k": k,
                    "most_novel": [{"id": r["id"], "max_similarity": round(r["max_similarity"], 5)} for r in novel],
                },
            )
        preds, conf, sims = _nearest(emb, self.classes, self.protos, self.support, self.support_labels, k)
        reject = options.get("min_similarity")
        rows = []
        for n, i in enumerate(ids):
            order = np.argsort(-sims[n])[:3]
            row = {
                "id": i,
                "prediction": preds[n],
                "confidence": float(conf[n]),
                "top3": [{"class": self.classes[j], "similarity": round(float(sims[n][j]), 5)} for j in order],
            }
            if reject is not None and conf[n] < float(reject):
                row["prediction"] = "unknown"
            rows.append(row)
        counts = Counter(r["prediction"] for r in rows)
        return PredictResult(rows, {"mode": "predict", "n": len(rows), "class_counts": dict(counts), "k": k})

    def _extend(self, ds: Dataset, emb: np.ndarray, out: Path) -> PredictResult:
        """Add new classes (bin codes) or more examples to the prototype bank without retraining the backbone."""
        if not ds.has_labels:
            raise ValueError("extend 需要以類別命名的資料夾（新 bin code 的範例影像）")
        labels = np.asarray(ds.y).astype(str)
        new_ids = np.asarray(ds.ids).astype(str)
        all_emb = np.concatenate([self.support, emb])
        all_labels = np.concatenate([self.support_labels, labels])
        all_ids = np.concatenate([self.support_ids, new_ids])
        classes, protos = _prototypes(all_emb, all_labels)
        added = sorted(set(labels.tolist()) - set(self.classes))
        meta = {k: v for k, v in self.meta.items() if k not in ("metrics", "classes", "inference_modes")}
        meta["support_per_class"] = dict(Counter(all_labels.tolist()))
        art = _save_bank(
            out.parent,
            classes,
            protos,
            all_emb,
            all_labels,
            all_ids,
            meta,
            self.meta.get("metrics") or {},
            set_default=True,
        )
        info(f"extend: +{len(labels)} examples, new classes={added}, total classes={len(classes)}")
        rows = [{"id": i, "label": lbl, "status": "added"} for i, lbl in zip(new_ids, labels, strict=True)]
        return PredictResult(
            rows,
            {
                "mode": "extend",
                "added_examples": len(labels),
                "new_classes": added,
                "classes": classes,
            },
            [art],
        )


class DinoPatchCoreTrainer(BaseTrainer):
    framework = "torch"
    inference_modes = ["score", "embed"]

    def fit(self, ds: Dataset) -> None:
        self.backbone_id = str(self.params.get("backbone", "dinov2-small"))
        self.k = int(self.params.get("k", 3))
        ratio = float(self.params.get("coreset_ratio", 0.1))
        dino = _Dino(self.ctx, self.backbone_id)
        paths = list(ds.X)
        y = _binary_anomaly_labels(ds.y) if ds.has_labels else None
        normal_idx = np.flatnonzero(y == 0) if y is not None else np.arange(len(paths))
        if len(normal_idx) == 0:
            raise ValueError("需要正常（good / normal）影像來建立記憶庫")
        tr, va_n = holdout(len(normal_idx), None, None)
        train_idx = normal_idx[tr]
        val_idx = np.concatenate([normal_idx[va_n], np.flatnonzero(y == 1)]) if y is not None else normal_idx[va_n]
        _, patches = dino.embed(
            [paths[i] for i in train_idx],
            patches=True,
            progress=lambda f: self.ctx.progress(0.05 + 0.5 * f, "training"),
        )
        n_img, L, D = patches.shape
        self.grid = round(np.sqrt(L))
        bank = patches.reshape(-1, D)
        rng = np.random.default_rng(42)
        keep = rng.choice(
            len(bank),
            size=max(1000, int(len(bank) * ratio)) if len(bank) > 1000 else len(bank),
            replace=False,
        )
        self.bank = bank[keep].astype(np.float16)
        info(f"patchcore: memory bank {len(self.bank):,} patches (from {n_img} images × {L}), D={D}")
        train_scores = self._image_scores(
            dino,
            [paths[i] for i in train_idx],
            progress=lambda f: self.ctx.progress(0.55 + 0.2 * f, "training"),
        )[0]
        self.threshold = float(np.percentile(train_scores, 99))
        val_scores = self._image_scores(
            dino,
            [paths[i] for i in val_idx],
            progress=lambda f: self.ctx.progress(0.75 + 0.15 * f, "training"),
        )[0]
        labels = y[val_idx] if (y is not None and len(np.unique(y[val_idx])) == 2) else None
        self.metrics = M.anomaly(val_scores, labels, self.threshold)
        self.meta.update(
            {
                "backbone": self.backbone_id,
                "k": self.k,
                "threshold": self.threshold,
                "grid": self.grid,
            }
        )
        info(f"{self.family}: " + ", ".join(f"{k}={v:.4f}" for k, v in self.metrics.items()))

    def _image_scores(self, dino: _Dino, paths: list[Path], progress=None):
        return patchcore_scores(dino, self.bank, self.k, paths, self.ctx, progress)

    def export(self, out: Path) -> list[ArtifactOut]:
        model_dir = out / "model"
        model_dir.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(model_dir / "memory_bank.npz", bank=self.bank)
        meta = {
            "backbone": self.backbone_id,
            "k": self.k,
            "threshold": self.threshold,
            "grid": self.grid,
            "metrics": self.metrics,
        }
        (model_dir / "metadata.json").write_text(jsonsafe.dumps(meta, indent=2), encoding="utf-8")
        return [
            ArtifactOut(
                name="dino_patchcore",
                kind="model",
                path="model",
                framework=self.framework,
                metrics=self.metrics,
                metadata=meta,
            )
        ]


def patchcore_scores(dino: _Dino, bank: np.ndarray, k: int, paths: list[Path], ctx, progress=None):
    """Per image: max over patches of the mean distance to the k nearest memory-bank patches; plus the patch map."""
    torch = dino.torch
    bank_t = torch.from_numpy(bank.astype(np.float32)).to(ctx.device)
    scores, maps = [], []
    for s in range(0, len(paths), 8):
        _, patches = dino.embed(paths[s : s + 8], patches=True, batch=8)
        p = torch.from_numpy(patches.astype(np.float32)).to(ctx.device)  # (B, L, D)
        B, L, D = p.shape
        flat = p.reshape(-1, D)
        dists = []
        for c in range(0, len(flat), 4096):
            d = torch.cdist(flat[c : c + 4096], bank_t)
            dists.append(d.topk(min(k, bank_t.shape[0]), largest=False).values.mean(dim=1))
        patch_scores = torch.cat(dists).reshape(B, L).cpu().numpy()
        scores.extend(patch_scores.max(axis=1).tolist())
        maps.extend(list(patch_scores))
        if progress:
            progress(min(1.0, (s + 8) / max(1, len(paths))))
    return np.asarray(scores, dtype=np.float32), maps


class DinoPatchCoreInferencer(BaseInferencer):
    def load(self, model_path: Path, metadata: dict[str, Any]) -> None:
        self.bank = np.load(model_path / "memory_bank.npz", allow_pickle=False)["bank"]
        local = model_path / "metadata.json"
        self.meta = {
            **(json.loads(local.read_text(encoding="utf-8")) if local.exists() else {}),
            **(metadata or {}),
        }
        self.dino = _Dino(self.ctx, str(self.meta.get("backbone", "dinov2-small")))

    def predict(self, ds: Dataset, mode: str, options: dict[str, Any], out: Path) -> PredictResult:
        out.mkdir(parents=True, exist_ok=True)
        ids = ds.ids or [Path(p).name for p in ds.X]
        paths = list(ds.X)
        if mode == "embed":
            emb = self.dino.embed(paths, progress=self.ctx.progress)
            np.save(out / "embeddings.npy", emb)
            rows = [{"id": i, "embedding": [round(float(v), 6) for v in e]} for i, e in zip(ids, emb, strict=True)]
            return PredictResult(
                rows,
                {"mode": mode, "n": len(rows)},
                [
                    ArtifactOut(
                        name="embeddings",
                        kind="report",
                        path="output/embeddings.npy",
                        framework="torch",
                    )
                ],
            )
        k = int(options.get("k", self.meta.get("k", 3)))
        scores, maps = patchcore_scores(
            self.dino, self.bank, k, paths, self.ctx, progress=lambda f: self.ctx.progress(0.9 * f)
        )
        threshold = float(options.get("threshold") or self.meta.get("threshold") or np.percentile(scores, 99))
        grid = int(self.meta.get("grid") or round(np.sqrt(len(maps[0]))))
        rows = []
        heat_dir = out / "heatmaps"
        save_heat = bool(options.get("save_heatmaps", True))
        seen: set[str] = set()
        for i, s, m in zip(ids, scores, maps, strict=True):
            hot = int(m.argmax())
            row = {
                "id": i,
                "anomaly_score": float(s),
                "is_anomaly": bool(s > threshold),
                "hot_patch_row": hot // grid,
                "hot_patch_col": hot % grid,
            }
            if save_heat:
                row["heatmap"] = _save_heatmap(heat_dir, _heatmap_name(i, seen), m.reshape(grid, grid), threshold)
            rows.append(row)
        extra = (
            [ArtifactOut(name="heatmaps", kind="report", path="output/heatmaps", framework="torch")]
            if save_heat and heat_dir.exists()
            else []
        )
        ranked = sorted(rows, key=lambda r: -r["anomaly_score"])[:20]
        return PredictResult(
            rows,
            {
                "mode": "score",
                "n": len(rows),
                "flagged": int(sum(r["is_anomaly"] for r in rows)),
                "threshold": threshold,
                "most_anomalous": [{"id": r["id"], "anomaly_score": r["anomaly_score"]} for r in ranked],
            },
            extra,
        )


def _heatmap_name(image_id: Any, seen: set[str]) -> str:
    """Heatmap file name from the image's relative path (``a/x.jpg`` → ``a__x.png``) so images with the same
    base name in different folders do not overwrite each other; ``seen`` breaks any remaining tie."""
    p = PurePosixPath(str(image_id).replace("\\", "/"))
    rel = (p.with_suffix("") if p.name else p).as_posix().strip("/")
    flat = re.sub(r"[^\w.\-]+", "_", rel.replace("/", "__")).strip("._") or "image"
    name, k = f"{flat}.png", 1
    while name in seen:
        k += 1
        name = f"{flat}_{k}.png"
    seen.add(name)
    return name


def _save_heatmap(heat_dir: Path, name: str, grid: np.ndarray, threshold: float) -> str:
    from PIL import Image

    heat_dir.mkdir(parents=True, exist_ok=True)
    norm = np.clip(grid / max(threshold * 1.5, 1e-6), 0, 1)
    img = Image.fromarray((norm * 255).astype(np.uint8), mode="L").resize((224, 224), Image.BILINEAR)
    img.save(heat_dir / name)
    return f"heatmaps/{name}"


__all__ = [
    "DinoFewShotInferencer",
    "DinoFewShotTrainer",
    "DinoPatchCoreInferencer",
    "DinoPatchCoreTrainer",
    "YoloInferencer",
    "YoloTrainer",
    "all_images",
]


# ---------------------------------------------------------------------------------------------------
# DINOv2 fine-tuning — linear probe, LoRA adapters (hand-written, no peft) or full fine-tune
# ---------------------------------------------------------------------------------------------------

# transformers ≥ 5 names the DINOv2 projections q_proj / k_proj / v_proj; 4.x used query / key / value
LORA_TARGETS = ("q_proj", "k_proj", "v_proj", "query", "key", "value")


def _lora_linear_class():  # built lazily: torch is only imported inside the trainers
    import math

    import torch

    class LoRALinear(torch.nn.Module):
        """``y = W x + (B A x) * alpha / rank`` with W frozen; only A and B train (B starts at zero so the first
        step reproduces the pretrained layer exactly)."""

        def __init__(self, base: torch.nn.Linear, rank: int, alpha: float) -> None:
            super().__init__()
            self.base = base
            for p in self.base.parameters():
                p.requires_grad_(False)
            self.lora_a = torch.nn.Parameter(torch.empty(rank, base.in_features))
            self.lora_b = torch.nn.Parameter(torch.zeros(base.out_features, rank))
            torch.nn.init.kaiming_uniform_(self.lora_a, a=math.sqrt(5))
            self.scaling = alpha / rank

        def forward(self, x):
            return self.base(x) + (x @ self.lora_a.T @ self.lora_b.T) * self.scaling

    return LoRALinear


def inject_lora(model, rank: int, alpha: float, targets: tuple[str, ...] = LORA_TARGETS) -> int:
    """Wrap every attention projection named in ``targets`` (DINOv2: q / k / v) with a LoRA adapter.
    Returns the number of wrapped layers."""
    import torch

    LoRALinear = _lora_linear_class()
    n = 0
    for name, module in list(model.named_modules()):
        if not isinstance(module, torch.nn.Linear) or name.rsplit(".", 1)[-1] not in targets:
            continue
        parent_name, _, attr = name.rpartition(".")
        parent = model.get_submodule(parent_name) if parent_name else model
        setattr(parent, attr, LoRALinear(module, rank, alpha))
        n += 1
    return n


def lora_state(model) -> dict[str, Any]:
    return {k: v.detach().cpu() for k, v in model.state_dict().items() if ".lora_" in k}


class _DinoFinetuneNet:
    """Backbone (from the zoo) + feature head shared by the trainer and the inferencer."""

    def __init__(self, ctx, backbone_id: str, method: str, n_classes: int, rank: int, alpha: float, backbone_dir=None):
        import torch
        from transformers import AutoImageProcessor, AutoModel

        zoo_path = ctx.weight(backbone_id)
        self.torch = torch
        self.ctx = ctx
        self.method = method
        self.processor = AutoImageProcessor.from_pretrained(str(zoo_path), local_files_only=True)
        src = backbone_dir if backbone_dir is not None else zoo_path
        self.backbone = AutoModel.from_pretrained(str(src), local_files_only=True)
        self.lora_layers = 0
        if method == "lora":
            self.lora_layers = inject_lora(self.backbone, rank, alpha)
        if method != "full":
            for name, p in self.backbone.named_parameters():
                p.requires_grad_(".lora_" in name)
        dim = int(self.backbone.config.hidden_size) * 2  # CLS + mean patch
        self.head = torch.nn.Sequential(torch.nn.LayerNorm(dim), torch.nn.Linear(dim, n_classes))
        self.backbone.to(ctx.device)
        self.head.to(ctx.device)
        self.feature_dim = dim

    def pixels(self, paths: list[Path], augment: bool = False):
        from PIL import Image, ImageOps

        imgs = []
        for p in paths:
            im = Image.open(p).convert("RGB")
            if augment and np.random.random() < 0.5:
                im = ImageOps.mirror(im)
            imgs.append(im)
        return self.processor(images=imgs, return_tensors="pt")["pixel_values"].to(self.ctx.device)

    def features(self, px):
        h = self.backbone(pixel_values=px).last_hidden_state
        return self.torch.cat([h[:, 0], h[:, 1:].mean(dim=1)], dim=1)

    def train_mode(self, on: bool) -> None:
        # a frozen backbone stays in eval (no dropout / drop-path noise) even while the head trains
        self.backbone.train(on and self.method == "full")
        self.head.train(on)

    def trainable_parameters(self):
        return [p for p in self.backbone.parameters() if p.requires_grad], list(self.head.parameters())

    def embed(self, paths: list[Path], batch: int, progress=None) -> np.ndarray:
        torch = self.torch
        self.train_mode(False)
        out = []
        with torch.no_grad():
            for k in range(0, len(paths), batch):
                f = self.features(self.pixels(paths[k : k + batch]))
                out.append(torch.nn.functional.normalize(f, dim=1).cpu().numpy())
                if progress:
                    progress(min(1.0, (k + batch) / max(1, len(paths))))
        return np.concatenate(out) if out else np.zeros((0, self.feature_dim), np.float32)

    def predict_proba(self, paths: list[Path], batch: int, progress=None) -> np.ndarray:
        torch = self.torch
        self.train_mode(False)
        out = []
        with torch.no_grad():
            for k in range(0, len(paths), batch):
                logits = self.head(self.features(self.pixels(paths[k : k + batch])))
                out.append(torch.softmax(logits, dim=-1).cpu().numpy())
                if progress:
                    progress(min(1.0, (k + batch) / max(1, len(paths))))
        return np.concatenate(out)


class DinoFinetuneTrainer(BaseTrainer):
    """Supervised fine-tuning of DINOv2 for image classification.

    ``method``: ``linear`` trains only a head on frozen features (fast, needs ~10+ images per class),
    ``lora`` adds low-rank adapters to the attention projections and trains them with the head (adapts the
    features to the domain while the base weights stay untouched; artifact = adapters + head, a few MB),
    ``full`` updates every parameter with a small ``backbone_lr`` (most capacity, most data and VRAM, artifact
    = a whole backbone). Pretrained weights always come from the zoo (``ctx.weight``)."""

    framework = "torch"
    inference_modes = ["predict", "embed", "retrieve"]

    def fit(self, ds: Dataset) -> None:
        import torch

        if not ds.has_labels:
            raise ValueError("分類微調需要以類別命名的資料夾")
        p = self.params
        self.backbone_id = str(p.get("backbone", "dinov2-small"))
        self.method = str(p.get("method", "lora"))
        if self.method not in ("linear", "lora", "full"):
            raise ValueError(f"method 必須是 linear / lora / full，不是 {self.method!r}")
        self.rank = int(p.get("rank", 8))
        self.alpha = float(p.get("lora_alpha", 2 * self.rank))
        epochs = int(p.get("epochs", 15))
        batch = int(p.get("batch", 16))
        lr = float(p.get("lr", 1e-3))
        backbone_lr = float(p.get("backbone_lr", 1e-5))
        augment = bool(p.get("augment", True))
        torch.manual_seed(int(p.get("seed", 42)))
        np.random.seed(int(p.get("seed", 42)))

        paths = [Path(x) for x in ds.X]
        labels = np.asarray(ds.y).astype(str)
        self.classes = sorted(set(labels.tolist()))
        index = {c: i for i, c in enumerate(self.classes)}
        y = np.array([index[v] for v in labels])
        tr, va = holdout(len(paths), labels, "classification")
        self.net = _DinoFinetuneNet(self.ctx, self.backbone_id, self.method, len(self.classes), self.rank, self.alpha)
        bb_params, _head_params = self.net.trainable_parameters()
        n_bb = sum(int(q.numel()) for q in bb_params)
        info(
            f"{self.family}: backbone={self.backbone_id} method={self.method} classes={len(self.classes)} "
            f"train={len(tr)} val={len(va)} trainable backbone params={n_bb} "
            f"(lora layers={self.net.lora_layers}) device={self.ctx.device}"
        )
        self.ctx.progress(0.02, "training")

        best: tuple[float, dict[str, Any], dict[str, Any], int] | None = None
        for attempt in range(2):
            try:
                best = self._train(paths, y, tr, va, epochs, batch, lr, backbone_lr, augment)
                break
            except torch.cuda.OutOfMemoryError:
                if attempt == 1 or batch <= 1:
                    raise
                warn(f"{self.family}: CUDA out of memory with batch={batch} → retrying with {batch // 2}")
                batch //= 2
                torch.cuda.empty_cache()
        assert best is not None
        _, head_state, bb_state, best_epoch = best
        self.net.head.load_state_dict(head_state)
        if bb_state:
            self.net.backbone.load_state_dict(bb_state, strict=False)
        self.batch = batch
        # reference bank (fine-tuned features of the training images) for retrieve mode
        self.ref_emb = self.net.embed(paths, batch)
        self.ref_labels, self.ref_ids = labels, np.asarray(ds.ids).astype(str)
        self.meta.update(
            {
                "classes": self.classes,
                "backbone": self.backbone_id,
                "method": self.method,
                "rank": self.rank if self.method == "lora" else None,
                "lora_alpha": self.alpha if self.method == "lora" else None,
                "feature_dim": self.net.feature_dim,
                "best_epoch": best_epoch,
                "train_per_class": dict(Counter(labels[tr].tolist())),
            }
        )
        info(f"{self.family}: best epoch {best_epoch} " + ", ".join(f"{k}={v:.4f}" for k, v in self.metrics.items()))

    def _train(self, paths, y, tr, va, epochs, batch, lr, backbone_lr, augment):
        import torch

        net = self.net
        bb_params, head_params = net.trainable_parameters()
        groups = [{"params": head_params, "lr": lr}]
        if bb_params:
            groups.append({"params": bb_params, "lr": backbone_lr if self.method == "full" else lr})
        opt = torch.optim.AdamW(groups, weight_decay=float(self.params.get("weight_decay", 0.01)))
        steps = epochs * max(1, int(np.ceil(len(tr) / batch)))
        sched = torch.optim.lr_scheduler.LambdaLR(
            opt, lambda s: min(1.0, (s + 1) / max(1, int(0.1 * steps))) * max(0.05, 1 - s / steps)
        )
        loss_fn = torch.nn.CrossEntropyLoss(label_smoothing=0.05)
        rng = np.random.default_rng(0)
        cached = None
        if self.method == "linear":  # frozen features never change: compute once, train the head on them
            feats = []
            with torch.no_grad():
                net.train_mode(False)
                for k in range(0, len(paths), batch):
                    feats.append(net.features(net.pixels(paths[k : k + batch])).cpu())
            cached = torch.cat(feats)
        best = None
        for epoch in range(1, epochs + 1):
            net.train_mode(True)
            order = rng.permutation(tr)
            total = 0.0
            for s in range(0, len(order), batch):
                idx = order[s : s + batch]
                yb = torch.as_tensor(y[idx]).to(self.ctx.device)
                if cached is not None:
                    logits = net.head(cached[idx].to(self.ctx.device))
                else:
                    logits = net.head(net.features(net.pixels([paths[i] for i in idx], augment=augment)))
                loss = loss_fn(logits, yb)
                opt.zero_grad(set_to_none=True)
                loss.backward()
                torch.nn.utils.clip_grad_norm_(head_params + bb_params, 1.0)
                opt.step()
                sched.step()
                total += float(loss.detach()) * len(idx)
                self.ctx.progress(0.02 + 0.9 * ((epoch - 1) + (s + len(idx)) / len(order)) / epochs, "training")
            if cached is not None:
                with torch.no_grad():
                    net.train_mode(False)
                    proba = torch.softmax(net.head(cached[va].to(self.ctx.device)), dim=-1).cpu().numpy()
            else:
                proba = net.predict_proba([paths[i] for i in va], batch)
            preds = proba.argmax(axis=1)
            self.metrics = M.classification(y[va], preds, proba)
            ep = {"loss": total / max(1, len(order)), **self.metrics}
            info(f"epoch {epoch}/{epochs} " + " ".join(f"{k}={v:.4f}" for k, v in ep.items()))
            score = self.metrics.get("f1_macro", 0.0)
            if best is None or score > best[0]:
                head_state = {k: v.detach().cpu().clone() for k, v in net.head.state_dict().items()}
                bb_state = (
                    lora_state(net.backbone)
                    if self.method == "lora"
                    else {k: v.detach().cpu().clone() for k, v in net.backbone.state_dict().items()}
                    if self.method == "full"
                    else {}
                )
                best = (score, head_state, bb_state, epoch)
            self.ctx.epoch(epoch, ep)
        assert best is not None
        self.metrics = {k: v for k, v in self.metrics.items()}
        return best

    def export(self, out: Path) -> list[ArtifactOut]:
        import torch

        model_dir = out / "model"
        model_dir.mkdir(parents=True, exist_ok=True)
        torch.save(self.net.head.state_dict(), model_dir / "head.pt")
        if self.method == "lora":
            torch.save(lora_state(self.net.backbone), model_dir / "lora.pt")
        elif self.method == "full":
            self.net.backbone.save_pretrained(model_dir / "backbone")
        np.savez_compressed(
            model_dir / "reference.npz",
            embeddings=self.ref_emb.astype(np.float32),
            labels=np.asarray(self.ref_labels, dtype=str),
            ids=np.asarray(self.ref_ids, dtype=str),
        )
        meta = {**self.meta, "metrics": self.metrics, "inference_modes": self.inference_modes}
        (model_dir / "metadata.json").write_text(jsonsafe.dumps(meta, indent=2), encoding="utf-8")
        return [
            ArtifactOut(
                name=f"dino_{self.method}",
                kind="model",
                path="model",
                framework=self.framework,
                metrics=self.metrics,
                metadata=meta,
            )
        ]


class DinoFinetuneInferencer(BaseInferencer):
    def load(self, model_path: Path, metadata: dict[str, Any]) -> None:
        import torch

        local = model_path / "metadata.json"
        self.meta = {
            **(json.loads(local.read_text(encoding="utf-8")) if local.exists() else {}),
            **(metadata or {}),
        }
        self.classes = [str(c) for c in self.meta["classes"]]
        method = str(self.meta.get("method", "lora"))
        self.net = _DinoFinetuneNet(
            self.ctx,
            str(self.meta.get("backbone", "dinov2-small")),
            method,
            len(self.classes),
            int(self.meta.get("rank") or 8),
            float(self.meta.get("lora_alpha") or 16),
            backbone_dir=model_path / "backbone" if method == "full" else None,
        )
        if method == "lora":
            _missing, unexpected = self.net.backbone.load_state_dict(
                torch.load(model_path / "lora.pt", map_location="cpu", weights_only=True), strict=False
            )
            if unexpected:
                raise ValueError(f"LoRA 權重與骨幹不符：{unexpected[:3]}")
        self.net.head.load_state_dict(torch.load(model_path / "head.pt", map_location="cpu", weights_only=True))
        self.net.head.to(self.ctx.device)
        ref = model_path / "reference.npz"
        if ref.exists():
            bank = np.load(ref, allow_pickle=False)
            self.ref_emb, self.ref_labels, self.ref_ids = bank["embeddings"], bank["labels"], bank["ids"]
        else:
            self.ref_emb = None
        self.batch = int(self.meta.get("batch", 16))
        info(f"dino_finetune: loaded {method} head for {len(self.classes)} classes")

    def predict(self, ds: Dataset, mode: str, options: dict[str, Any], out: Path) -> PredictResult:
        out.mkdir(parents=True, exist_ok=True)
        paths = [Path(x) for x in ds.X]
        ids = ds.ids or [p.name for p in paths]
        batch = int(options.get("batch", self.batch))
        if mode == "embed":
            emb = self.net.embed(paths, batch, progress=lambda f: self.ctx.progress(0.9 * f))
            np.save(out / "embeddings.npy", emb)
            rows = [{"id": i, "embedding": [round(float(v), 6) for v in e]} for i, e in zip(ids, emb, strict=True)]
            return PredictResult(
                rows,
                {"mode": mode, "n": len(rows), "dim": int(emb.shape[1])},
                [ArtifactOut(name="embeddings", kind="report", path="output/embeddings.npy", framework="torch")],
            )
        if mode == "retrieve":
            if self.ref_emb is None:
                raise ValueError("這個模型沒有參考影像庫，無法 retrieve")
            k = int(options.get("k", 5))
            emb = self.net.embed(paths, batch, progress=lambda f: self.ctx.progress(0.9 * f))
            sims = emb @ self.ref_emb.T
            rows = []
            for n, i in enumerate(ids):
                order = np.argsort(-sims[n])
                rows.append(
                    {
                        "id": i,
                        "max_similarity": float(sims[n][order[0]]),
                        "most_similar": [
                            {
                                "id": str(self.ref_ids[j]),
                                "label": str(self.ref_labels[j]),
                                "similarity": round(float(sims[n][j]), 5),
                            }
                            for j in order[:k]
                        ],
                    }
                )
            return PredictResult(rows, {"mode": mode, "n": len(rows), "k": k})
        proba = self.net.predict_proba(paths, batch, progress=lambda f: self.ctx.progress(0.9 * f))
        reject = options.get("min_confidence")
        rows = []
        for n, i in enumerate(ids):
            order = np.argsort(-proba[n])[:3]
            pred = self.classes[int(order[0])]
            conf = float(proba[n][order[0]])
            if reject is not None and conf < float(reject):
                pred = "unknown"
            rows.append(
                {
                    "id": i,
                    "prediction": pred,
                    "confidence": conf,
                    "top3": [
                        {"class": self.classes[int(j)], "probability": round(float(proba[n][j]), 5)} for j in order
                    ],
                }
            )
        counts = Counter(r["prediction"] for r in rows)
        return PredictResult(rows, {"mode": "predict", "n": len(rows), "class_counts": dict(counts)})
