"""Vision families: YOLO (ultralytics), DINOv2 / v3 frozen-feature classification (prototype / kNN / linear / SVM
heads, optional PatchCore two-stage defect classification), DINO LoRA fine-tuning and DINO PatchCore anomaly
detection.

Weights never come from the network: YOLO checkpoints and DINOv2 folders are resolved through ctx.weight()
(the model zoo). `pretrained: false` builds YOLO from its architecture yaml (bundled with ultralytics).
"""

from __future__ import annotations

import json
import os
import shutil
from collections import Counter
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np

from trainer import jsonsafe
from trainer import metrics as M
from trainer.data.image import all_images, class_folders
from trainer.data.split import holdout
from trainer.dataset import Dataset
from trainer.log import info, warn
from trainer.models.base import ArtifactOut, BaseInferencer, BaseTrainer, PredictResult
from trainer.models.dino_features import (
    SCORE_AGGS,
    FeatureSpec,
    FewShotHead,
    aggregate_neighborhood,
    aggregate_scores,
    backbone_kind,
    fuse_blocks,
    fuse_tokens,
    patch_reference,
    resolve_head,
    resolve_layers,
    select_layers,
)
from trainer.models.tabular import _binary_anomaly_labels
from trainer.retrieval import neighbour_rows

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


# the shared `augment` ops → ultralytics training hyper-parameters (value when the op is on / off)
YOLO_AUGMENT: dict[str, dict[str, tuple[float, float]]] = {
    "hflip": {"fliplr": (0.5, 0.0)},
    "vflip": {"flipud": (0.5, 0.0)},
    "rotate90": {"degrees": (90.0, 0.0)},
    "crop": {"scale": (0.5, 0.0), "translate": (0.1, 0.0)},
    "brightness": {"hsv_v": (0.4, 0.0)},
}


def yolo_augment_kwargs(value: Any) -> dict[str, float]:
    """``augment`` param (list / comma string / bool) → ultralytics kwargs; every op the family knows is set
    explicitly so unchecking one really turns it off. Ops YOLO has no knob for (contrast) are ignored with a
    warning."""
    ops = parse_augment(value)
    unknown = [o for o in ops if o not in YOLO_AUGMENT]
    if unknown:
        warn(f"yolo: augment {unknown} has no ultralytics equivalent, ignored")
    out: dict[str, Any] = {}
    for op, knobs in YOLO_AUGMENT.items():
        for key, (on, off) in knobs.items():
            out[key] = on if op in ops else off
    if not ops:  # "none" really means none: ultralytics' own defaults (mosaic, hue / saturation, RandAugment,
        # random erasing) go too; with any op ticked they stay at their defaults
        out.update(YOLO_NO_AUGMENT)
    return out


# ultralytics' built-in augmentations that are on by default; switched off when ``augment`` is empty
YOLO_NO_AUGMENT: dict[str, Any] = {
    "mosaic": 0.0,
    "mixup": 0.0,
    "copy_paste": 0.0,
    "hsv_h": 0.0,
    "hsv_s": 0.0,
    "erasing": 0.0,
    "auto_augment": None,
}


YOLO_FREEZE_BELOW = 200  # freeze=auto: with fewer images than this, train only the neck + head


def resolve_freeze(value: Any, n_images: int, n_backbone: int = 10, pretrained: bool = True) -> tuple[int, str]:
    """``freeze`` param → (modules to freeze, reason). ``auto`` freezes the backbone (its module count comes
    from the model yaml: 10 for detection / segmentation, 9 for classification) on small datasets; a network
    trained from scratch has nothing worth freezing."""
    if value in (None, "", "auto"):
        if not pretrained:
            return 0, "from scratch → nothing to freeze"
        if n_images < YOLO_FREEZE_BELOW:
            return n_backbone, f"{n_images} images < {YOLO_FREEZE_BELOW} → backbone ({n_backbone} modules) frozen"
        return 0, f"{n_images} images → whole network trains"
    return int(value), "chosen by the user"


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
        if "augment" in self.params:
            aug = yolo_augment_kwargs(self.params["augment"])
            info("yolo: augment " + ", ".join(f"{k}={v}" for k, v in aug.items()))
            kwargs.update(aug)
        n_backbone = len((getattr(model.model, "yaml", None) or {}).get("backbone", [])) or 10
        freeze, why = resolve_freeze(
            self.params.get("freeze", "auto"), len(ds), n_backbone, bool(self.params.get("pretrained", True))
        )
        if freeze > 0:  # keep the first N layers (the backbone) at their pretrained values: faster, less overfit
            kwargs["freeze"] = freeze
        info(f"yolo: freeze={freeze} ({why})")
        self.meta["resolved"] = {"freeze": freeze}
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
# DINOv2 / DINOv3 (frozen backbone) — patch-token features, few-shot heads, PatchCore patch bank
# ---------------------------------------------------------------------------------------------------


def special_tokens(config) -> int:
    """Register tokens that sit between CLS and the patch tokens (DINOv3: 4; DINOv2: 0)."""
    return int(getattr(config, "num_register_tokens", 0) or 0)


ATTENTION_MAX = 2000  # overlays written per inference run (one PNG per image)
NORMAL_FOLDERS = ("good", "normal", "ok", "pass")  # class folder names that mean "no defect"
BANK_MAX_PATCHES = 100_000  # coreset_ratio=auto keeps the memory bank at most this big
BANK_AUGMENT_BELOW = 20  # bank_augment=auto: flip / rotate the normal images when there are fewer than this
PROJECT_ABOVE = 1536  # fused patch features wider than this are projected down (random projection) to PROJECT_TO
PROJECT_TO = 1024


def _overlays(out: Path, ids: list[Any], paths: list[Path], values: list[np.ndarray], processor) -> list[str | None]:
    """One RGBA overlay per image from a per-patch value vector (similarity, CAM, anomaly score) under
    ``out/attention/``; returns the relative path per image (None past ATTENTION_MAX)."""
    from PIL import Image

    from trainer import viz

    names: set[str] = set()
    rels: list[str | None] = []
    limit = min(len(paths), ATTENTION_MAX)
    if len(paths) > limit:
        warn(f"overlays written for the first {limit} of {len(paths)} images")
    for n in range(len(paths)):
        if n >= limit:
            rels.append(None)
            continue
        with Image.open(paths[n]) as im:
            size = im.size
        box = viz.crop_box(size[0], size[1], processor)
        name = _heatmap_name(ids[n], names)
        rels.append("attention/" + viz.save_overlay(out / "attention", name, viz.patch_grid(values[n]), size, box))
    return rels


def _attention_maps(
    out: Path, ids: list[Any], paths: list[Path], patches: np.ndarray, refs: np.ndarray, processor, enabled: bool
) -> list[str | None]:
    """Per image: cosine similarity of every patch token to its reference vector (the matched prototype or
    neighbour, or a linear head's class weights = CAM)."""
    if not enabled:
        return [None] * len(paths)
    values = [patches[n].astype(np.float32) @ refs[n].astype(np.float32) for n in range(len(paths))]
    return _overlays(out, ids, paths, values, processor)


def _neighbour_rows(sims: np.ndarray, order: str, k: int, labels: np.ndarray, ids: np.ndarray) -> dict[str, Any]:
    """retrieve: the k most similar and / or least similar reference items for one query (see trainer.retrieval)."""
    return neighbour_rows(sims, order, k, labels, ids)


def _set_image_size(processor, image_size: int | None) -> None:
    """``image_size``: resize the short side to it and centre-crop a square of it. 224 is the pretraining size;
    336 / 448 give 2.25 / 4× more patches for fine texture at 2.25 / 4× the compute."""
    if not image_size:
        return
    s = int(image_size)
    try:
        processor.size = {"shortest_edge": s}
        processor.crop_size = {"height": s, "width": s}
        processor.do_center_crop = True
        processor.do_resize = True
    except Exception as e:  # pragma: no cover - a processor without these knobs keeps its own size
        warn(f"image_size={s} ignored: {e}")


def _load_backbone(path: Path):
    from transformers import AutoModel

    return AutoModel.from_pretrained(str(path), local_files_only=True)


def _final_norm(model):
    return getattr(model, "layernorm", None) or getattr(model, "norm", None)


class _Dino:
    """Frozen DINOv2 / v3 from the zoo, driven by a FeatureSpec: reads the selected layers (final norm applied
    to each), keeps the patch tokens only, averages them per layer for the image vector and concatenates the
    layers; optionally returns the fused, L2-normalised patch grid (with PatchCore's neighbourhood mean)."""

    def __init__(self, ctx, backbone_id: str, spec: FeatureSpec | None = None, *, model=None, processor=None) -> None:
        """``model`` / ``processor``: an already built (e.g. LoRA- or fully fine-tuned) backbone to read features
        from instead of the zoo weights."""
        import torch
        from transformers import AutoImageProcessor

        spec = spec or FeatureSpec()
        path = ctx.weight(backbone_id)
        self.ctx = ctx
        self.torch = torch
        self.backbone_id = backbone_id
        self.processor = processor or AutoImageProcessor.from_pretrained(str(path), local_files_only=True)
        _set_image_size(self.processor, spec.image_size)
        self.model = (model if model is not None else _load_backbone(path)).to(ctx.device).eval()
        self.adapted = model is not None
        cfg = self.model.config
        self.kind = backbone_kind(backbone_id, getattr(cfg, "model_type", None))
        self.n_layers = int(cfg.num_hidden_layers)
        self.hidden = int(cfg.hidden_size)
        self.final_norm = _final_norm(self.model)
        self.layers = resolve_layers(spec.layers, self.n_layers, self.kind)
        # the artifact stores the resolved layer ids (a preset depends on the backbone depth)
        self.spec = spec if spec.layers == "auto" else replace(spec, layers=self.layers)
        # token layout: [CLS] [register × n (DINOv3)] [patch × L]; only the patches form the spatial grid
        self.n_special = 1 + special_tokens(cfg)
        info(
            f"dino: {'fine-tuned ' if self.adapted else 'loaded '}{backbone_id} ({self.kind}, {self.n_layers} layers, "
            f"hidden={self.hidden}) from {path} on {ctx.device}; {self.spec.describe()} → layers {list(self.layers)}, "
            f"feature dim={self.feature_dim}"
        )

    @property
    def feature_dim(self) -> int:
        return self.hidden * len(self.layers)

    @property
    def patch_dim(self) -> int:
        return self.hidden * len(self.layers)

    def with_layers(self, layers: tuple[int, ...]) -> _Dino:
        """Same model, a narrower layer selection (used after ``layers: auto`` picked)."""
        import copy

        other = copy.copy(self)
        other.layers = tuple(layers)
        other.spec = replace(self.spec, layers=tuple(layers))
        return other

    def _batches(self, items: list[Any], batch: int):
        """``items`` are paths or already-open PIL images."""
        from PIL import Image

        for s in range(0, len(items), batch):
            imgs = [
                x.convert("RGB") if isinstance(x, Image.Image) else Image.open(x).convert("RGB")
                for x in items[s : s + batch]
            ]
            yield self.processor(images=imgs, return_tensors="pt")["pixel_values"].to(self.ctx.device)

    def forward(self, px):
        """→ patch tokens per selected layer (final norm applied; CLS / register tokens dropped)."""
        hs = self.model(pixel_values=px, output_hidden_states=True).hidden_states  # index k = after block k
        toks = []
        for layer in self.layers:
            h = hs[layer]
            if self.final_norm is not None:
                h = self.final_norm(h)
            toks.append(h[:, self.n_special :])
        return toks

    def fuse_patches(self, tok_list):
        """Per-layer patch tokens → the fused, L2-normalised patch grid (B, L, patch_dim), after the
        neighbourhood mean when the spec asks for it."""
        return fuse_tokens([aggregate_neighborhood(t, self.spec.neighborhood) for t in tok_list])

    def fuse(self, blocks: np.ndarray) -> np.ndarray:
        return fuse_blocks(blocks)

    def embed(self, items: list[Any], *, patches: bool = False, batch: int = 16, progress=None, per_layer=False):
        """Fused, L2-normalised image vectors (N, feature_dim); with ``patches`` also the fused patch grid
        (N, L, patch_dim) in float16; with ``per_layer`` the per-layer mean-pooled blocks (N, n_layers_used,
        hidden) instead of the fused vector (the caller fuses a subset)."""
        torch = self.torch
        block_out, patch_out = [], []
        with torch.no_grad():
            for k, px in enumerate(self._batches(items, batch)):
                toks = self.forward(px)
                block_out.append(torch.stack([t.mean(dim=1) for t in toks], dim=1).float().cpu().numpy())
                if patches:
                    patch_out.append(self.fuse_patches(toks).cpu().numpy().astype(np.float16))
                if progress:
                    progress(min(1.0, (k + 1) * batch / max(1, len(items))))
        blocks = np.concatenate(block_out) if block_out else np.zeros((0, len(self.layers), self.hidden), np.float32)
        emb = blocks if per_layer else self.fuse(blocks)
        if not patches:
            return emb
        return emb, (np.concatenate(patch_out) if patch_out else None)

    def patch_reference(self, vec: np.ndarray) -> np.ndarray:
        return patch_reference(vec, self.hidden, len(self.layers))


def _auto_layers(dino: _Dino, paths: list[Path], labels: np.ndarray, progress=None) -> tuple[_Dino, np.ndarray, list]:
    """``layers: auto``: read every layer once, score each on the labelled images, keep the best few and fuse
    only those (no second pass over the backbone)."""
    blocks = dino.embed(paths, per_layer=True, progress=progress)
    chosen, report = select_layers(blocks, labels, dino.layers)
    sel = [dino.layers.index(layer) for layer in chosen]
    info(
        "layers=auto: "
        + " ".join(
            f"L{s['layer']}:acc={s['loo_accuracy']:.2f}/fisher={s['fisher']:.2f}{'*' if s['selected'] else ''}"
            for s in report
        )
        + f" → {list(chosen)}"
    )
    narrowed = dino.with_layers(chosen)
    return narrowed, narrowed.fuse(blocks[:, sel, :]), report


# --- PatchCore patch bank ---------------------------------------------------------------------------------


def _patch_scores(bank_t, patches: np.ndarray, k: int, torch) -> np.ndarray:
    """(N, L) mean distance of every patch to its k nearest memory-bank patches."""
    p = torch.from_numpy(np.asarray(patches, dtype=np.float32)).to(bank_t.device)
    B, L, D = p.shape
    flat = p.reshape(-1, D)
    dists = []
    for c in range(0, len(flat), 4096):
        d = torch.cdist(flat[c : c + 4096], bank_t)
        dists.append(d.topk(min(k, bank_t.shape[0]), largest=False).values.mean(dim=1))
    return torch.cat(dists).reshape(B, L).cpu().numpy()


def _coreset(flat: np.ndarray, ratio: float, seed: int = 42) -> np.ndarray:
    rng = np.random.default_rng(seed)
    n = len(flat)
    size = max(1000, int(n * ratio)) if n > 1000 else n
    return flat[rng.choice(n, size=min(n, size), replace=False)].astype(np.float16)


def resolve_coreset_ratio(value: Any, total_patches: int) -> tuple[float, str]:
    """``coreset_ratio`` → (ratio, reason). ``auto`` keeps the bank at most BANK_MAX_PATCHES patches."""
    if value in (None, "", "auto"):
        ratio = min(1.0, BANK_MAX_PATCHES / max(1, total_patches))
        return ratio, f"{total_patches:,} normal patches → keep {ratio:.0%} (bank ≤ {BANK_MAX_PATCHES:,})"
    return float(value), "chosen by the user"


def resolve_flag(value: Any, auto_value: bool, reason: str) -> tuple[bool, str]:
    s = str(value if value is not None else "auto").lower()
    if s in ("auto", ""):
        return auto_value, reason
    return s in ("on", "true", "1", "yes"), "chosen by the user"


def resolve_score_agg(value: Any, n_patches: int) -> tuple[str, str]:
    """``score_agg`` → (agg, reason). ``auto`` = ``max`` on coarse grids (≤ 256 patches: one patch is already
    a large area), ``top1`` on finer ones (robust to a single noisy patch)."""
    s = str(value or "auto").lower()
    if s == "auto":
        if n_patches <= 256:
            return "max", f"{n_patches} patches per image → max"
        return "top1", f"{n_patches} patches per image → mean of the top 1 %"
    if s not in SCORE_AGGS:
        raise ValueError(f"score_agg 必須是 auto / {' / '.join(SCORE_AGGS)}，不是 {value!r}")
    return s, "chosen by the user"


def _projection(dim_in: int, dim_out: int, seed: int = 0) -> np.ndarray | None:
    """Fixed Gaussian random projection (Johnson–Lindenstrauss) applied to very wide fused patch features;
    regenerated from the seed at inference, never stored."""
    if dim_out <= 0 or dim_out >= dim_in:
        return None
    rng = np.random.default_rng(seed)
    return (rng.standard_normal((dim_in, dim_out)) / np.sqrt(dim_out)).astype(np.float32)


def _project(patches: np.ndarray, proj: np.ndarray | None) -> np.ndarray:
    if proj is None:
        return patches
    flat = patches.reshape(-1, patches.shape[-1]).astype(np.float32) @ proj
    flat /= np.linalg.norm(flat, axis=1, keepdims=True) + 1e-9
    return flat.reshape(*patches.shape[:-1], proj.shape[1]).astype(np.float16)


def _augmented(path: Path) -> list[Any]:
    """The image plus its flips and a 90° rotation (bank augmentation for very small normal sets)."""
    from PIL import Image, ImageOps

    im = Image.open(path).convert("RGB")
    return [im, ImageOps.mirror(im), ImageOps.flip(im), im.rotate(90, expand=True)]


def _resolve_normal_class(classes: list[str], wanted: Any) -> str | None:
    """The class that means "no defect": ``normal_class`` if given (must exist), else a folder named like
    good / normal / ok / pass."""
    if wanted not in (None, ""):
        w = str(wanted)
        for c in classes:
            if c.lower() == w.lower():
                return c
        raise ValueError(f"normal_class={w!r} 不在資料的類別裡（{', '.join(classes)}）")
    hits = [c for c in classes if c.lower() in NORMAL_FOLDERS]
    return hits[0] if len(hits) == 1 else None


class _PatchBank:
    """PatchCore memory bank of the normal images' patch tokens. Patch score = mean distance to the k nearest
    bank patches; image score = ``max`` or ``top1`` over the patches; threshold = P99 of held-out normal
    images. Shared by the anomaly-detection family and the two-stage classifier (where the anomalous patches
    above the threshold are pooled, score-weighted, into a defect descriptor)."""

    def __init__(
        self,
        bank: np.ndarray,
        threshold: float,
        grid: int,
        *,
        k: int = 3,
        score_agg: str = "max",
        normal_class: str | None = None,
        coreset_ratio: float = 0.1,
        projection: dict[str, Any] | None = None,
        defect_global: bool = True,
        percentile: float = 99.0,
    ) -> None:
        self.bank = bank
        self.threshold = threshold
        self.grid = grid
        self.k = k
        self.score_agg = score_agg
        self.normal_class = normal_class
        self.coreset_ratio = coreset_ratio
        self.projection = projection
        self.proj = (
            _projection(int(projection["dim_in"]), int(projection["dim_out"]), int(projection.get("seed", 0)))
            if projection
            else None
        )
        self.defect_global = defect_global
        self.percentile = percentile
        self._bank_t = None

    def meta(self) -> dict[str, Any]:
        return {
            "threshold": self.threshold,
            "grid": self.grid,
            "k": self.k,
            "score_agg": self.score_agg,
            "normal_class": self.normal_class,
            "coreset_ratio": self.coreset_ratio,
            "projection": self.projection,
            "defect_global": self.defect_global,
            "percentile": self.percentile,
            "patches": len(self.bank),
            "patch_dim": int(self.bank.shape[1]),
        }

    @classmethod
    def from_meta(cls, meta: dict[str, Any], bank: np.ndarray) -> _PatchBank:
        return cls(
            bank,
            float(meta["threshold"]),
            int(meta["grid"]),
            k=int(meta.get("k") or 3),
            score_agg=str(meta.get("score_agg") or "max"),
            normal_class=meta.get("normal_class"),
            coreset_ratio=float(meta.get("coreset_ratio") or 0.1),
            projection=meta.get("projection"),
            defect_global=bool(meta.get("defect_global", True)),
            percentile=float(meta.get("percentile") or 99),
        )

    @classmethod
    def fit(
        cls,
        dino: _Dino,
        normal_paths: list[Path],
        params: dict[str, Any],
        *,
        normal_class: str | None = None,
        progress=None,
        resolved: dict[str, Any] | None = None,
    ) -> _PatchBank:
        """Build the bank from ``normal_paths`` (20 % held out for the threshold; with < 2 images the bank and
        the threshold come from the same images, which only a user-set threshold can fix)."""
        if len(normal_paths) < 2:
            raise ValueError("PatchCore 需要至少 2 張正常影像來建立記憶庫並估門檻")
        rng = np.random.default_rng(42)
        perm = rng.permutation(len(normal_paths))
        n_hold = max(1, round(len(perm) * 0.2))
        hold = [normal_paths[i] for i in perm[:n_hold]]
        train = [normal_paths[i] for i in perm[n_hold:]]
        k = int(params.get("bank_k", params.get("k", 3)) or 3)
        pct = float(params.get("patch_percentile", 99))
        augment, why_aug = resolve_flag(
            params.get("bank_augment", "auto"),
            len(train) < BANK_AUGMENT_BELOW,
            f"{len(train)} normal images {'<' if len(train) < BANK_AUGMENT_BELOW else '≥'} {BANK_AUGMENT_BELOW}",
        )
        items: list[Any] = []
        for p in train:
            items.extend(_augmented(p) if augment else [p])
        _, patches = dino.embed(items, patches=True, progress=lambda f: progress(0.5 * f) if progress else None)
        n, L, D = patches.shape
        projection = None
        if D > PROJECT_ABOVE:
            projection = {"dim_in": D, "dim_out": PROJECT_TO, "seed": int(params.get("seed", 0))}
            patches = _project(patches, _projection(D, PROJECT_TO, projection["seed"]))
        ratio, why_ratio = resolve_coreset_ratio(params.get("coreset_ratio", "auto"), n * L)
        agg, why_agg = resolve_score_agg(params.get("score_agg", "auto"), L)
        bank = cls(
            _coreset(patches.reshape(-1, patches.shape[-1]), ratio),
            0.0,
            round(np.sqrt(L)),
            k=k,
            score_agg=agg,
            normal_class=normal_class,
            coreset_ratio=ratio,
            projection=projection,
            defect_global=bool(params.get("defect_global", True)),
            percentile=pct,
        )
        scores, _ = bank.score(dino, hold, progress=lambda f: progress(0.5 + 0.5 * f) if progress else None)
        bank.threshold = float(np.percentile(scores, pct)) if len(scores) > 1 else float(scores.max() * 1.1 + 1e-6)
        info(
            f"patchcore: bank={len(bank.bank):,} patches from {len(train)} normal images"
            f"{' ×4 augmented' if augment else ''} × {L} patches, D={bank.bank.shape[1]}"
            f"{' (projected from ' + str(D) + ')' if projection else ''}; coreset_ratio={ratio:.3f} ({why_ratio}); "
            f"score_agg={agg} ({why_agg}); bank_augment={augment} ({why_aug}); "
            f"threshold={bank.threshold:.4f} (P{pct:g} of {len(hold)} held-out normal images)"
        )
        if resolved is not None:
            resolved.update({"coreset_ratio": round(ratio, 4), "score_agg": agg, "bank_augment": augment, "bank_k": k})
        return bank

    def bank_tensor(self, torch, device):
        if self._bank_t is None or str(self._bank_t.device) != str(device):
            self._bank_t = torch.from_numpy(self.bank.astype(np.float32)).to(device)
        return self._bank_t

    def score_patches(self, dino: _Dino, patches: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        maps = _patch_scores(
            self.bank_tensor(dino.torch, dino.ctx.device), _project(patches, self.proj), self.k, dino.torch
        )
        return aggregate_scores(maps, self.score_agg), maps

    def score(
        self, dino: _Dino, paths: list[Any], progress=None, chunk: int = 16
    ) -> tuple[np.ndarray, list[np.ndarray]]:
        scores, maps = [], []
        for s in range(0, len(paths), chunk):
            _, patches = dino.embed(paths[s : s + chunk], patches=True, batch=chunk)
            sc, mp = self.score_patches(dino, patches)
            scores.extend(sc.tolist())
            maps.extend(list(mp))
            if progress:
                progress(min(1.0, (s + chunk) / max(1, len(paths))))
        return np.asarray(scores, dtype=np.float32), maps

    def descriptor(self, patches: np.ndarray, pmap: np.ndarray, emb: np.ndarray | None) -> np.ndarray:
        """Score-weighted mean of the anomalous patches (fallback: the top 5 % patches), unit length, optionally
        concatenated with the global image vector."""
        hot = pmap > self.threshold
        if not hot.any():
            hot = pmap >= np.percentile(pmap, 95)
        w = (pmap * hot).astype(np.float32)
        d = (w[:, None] * patches.astype(np.float32)).sum(axis=0) / (w.sum() + 1e-9)
        d = d / (np.linalg.norm(d) + 1e-9)
        if self.defect_global and emb is not None:
            d = np.concatenate([d, np.asarray(emb, dtype=np.float32)])
            d = d / (np.linalg.norm(d) + 1e-9)
        return d.astype(np.float32)

    def analyse(self, dino: _Dino, paths: list[Path], emb: np.ndarray, progress=None, chunk: int = 16):
        """→ image scores (N,), patch maps (list of (L,)), defect descriptors (N, Dd)."""
        scores, maps, descs = [], [], []
        for s in range(0, len(paths), chunk):
            _, patches = dino.embed(paths[s : s + chunk], patches=True, batch=chunk)
            sc, mp = self.score_patches(dino, patches)
            for j in range(len(sc)):
                scores.append(float(sc[j]))
                maps.append(mp[j])
                descs.append(self.descriptor(patches[j], mp[j], emb[s + j]))
            if progress:
                progress(min(1.0, (s + chunk) / max(1, len(paths))))
        return np.asarray(scores, dtype=np.float32), maps, (np.stack(descs) if descs else np.zeros((0, 1), np.float32))


# --- few-shot classification (frozen features) -------------------------------------------------------------


FINETUNE_MODES = ("none", "lora", "full")


def resolve_finetune(value: Any) -> str:
    s = str(value if value is not None else "none").strip().lower()
    if s in ("", "no", "false", "off", "0", "frozen"):
        return "none"
    if s in ("yes", "true", "on", "1"):
        return "lora"
    if s not in FINETUNE_MODES:
        raise ValueError(f"finetune 必須是 {' / '.join(FINETUNE_MODES)}，不是 {value!r}")
    return s


class _ScaledProgress:
    """Map a nested trainer's 0 … 1 progress into the ``lo`` … ``hi`` slice of the outer job's bar."""

    def __init__(self, ctx, lo: float, hi: float) -> None:
        self.ctx, self.lo, self.hi = ctx, lo, hi

    def __enter__(self):
        self.outer = self.ctx.on_progress
        outer, lo, hi = self.outer, self.lo, self.hi
        self.ctx.on_progress = (lambda f, stage: outer(lo + (hi - lo) * f, stage)) if outer else None
        return self

    def __exit__(self, *exc) -> None:
        self.ctx.on_progress = self.outer


class DinoTrainer(BaseTrainer):
    """The DINO image-classification family. Steps: (1) optional backbone fine-tuning — ``finetune`` = ``none``
    (frozen, default) / ``lora`` (adapters on the attention projections, default when fine-tuning) / ``full``
    (every weight) trained with a linear head on the labelled folders; (2) features from the (fine-tuned)
    backbone: ``layers`` (last / cross / list) and ``image_size``, patch tokens only, mean per layer, layers
    concatenated; (3) a ``head`` (auto / prototype / knn / linear / svm) on those vectors. With a normal class
    (folder good / normal / ok / pass, or ``normal_class``) and ``patchcore`` on (``auto`` = whenever such a
    class exists) a PatchCore bank of the normal patches decides normal vs. defect first, and only the anomalous
    patches are classified among the defect folders."""

    framework = "torch"
    inference_modes = ["predict", "embed", "retrieve", "extend"]

    def fit(self, ds: Dataset) -> None:
        if not ds.has_labels:
            raise ValueError("分類需要以類別（bin code）命名的資料夾")
        p = self.params
        self.backbone_id = str(p.get("backbone", "dinov2-small"))
        spec = FeatureSpec.from_params(p)
        paths = [Path(x) for x in ds.X]
        labels = np.asarray(ds.y).astype(str)
        classes = sorted(set(labels.tolist()))
        counts = Counter(labels.tolist())
        resolved: dict[str, Any] = {}
        self.finetune = resolve_finetune(p.get("finetune"))
        self.ft: DinoFinetuneTrainer | None = None
        resolved["finetune"] = self.finetune
        start = 0.05
        if self.finetune != "none":
            self.ft = DinoFinetuneTrainer(self.family, self.task, {**p, "method": self.finetune}, self.ctx)
            with _ScaledProgress(self.ctx, 0.02, 0.5):
                self.ft.fit(ds)
            self.ft.net.train_mode(False)
            dino = _Dino(self.ctx, self.backbone_id, spec, model=self.ft.net.backbone, processor=self.ft.net.processor)
            resolved.update({k: v for k, v in self.ft.meta.get("resolved", {}).items() if k != "layers"})
            start = 0.5
        else:
            dino = _Dino(self.ctx, self.backbone_id, spec)
        span = 0.5 if self.finetune == "none" else 0.25
        self.ctx.progress(start, "training")
        self.layer_report = None
        if spec.layers == "auto":
            dino, emb, self.layer_report = _auto_layers(
                dino, paths, labels, progress=lambda f: self.ctx.progress(start + span * f, "training")
            )
        else:
            emb = dino.embed(paths, progress=lambda f: self.ctx.progress(start + span * f, "training"))
        self.spec = dino.spec
        resolved["layers"] = list(dino.layers)
        self.emb, self.labels, self.ids = emb, labels, np.asarray(ds.ids).astype(str)

        # --- PatchCore (two-stage) ----------------------------------------------------------------
        self.normal_class = _resolve_normal_class(classes, p.get("normal_class"))
        want_bank, why_bank = resolve_flag(
            p.get("patchcore", "auto"),
            self.normal_class is not None and len(classes) >= 2,
            f"normal class {self.normal_class!r}"
            if self.normal_class
            else "no normal folder (good / normal / ok / pass)",
        )
        self.bank: _PatchBank | None = None
        self.defect_head: FewShotHead | None = None
        self.defect_desc: np.ndarray | None = None
        if want_bank:
            if self.normal_class is None:
                raise ValueError(
                    "patchcore=on 需要正常類別：資料夾取名 good / normal / ok / pass，或在參數設定 normal_class"
                )
            if len(classes) < 2:
                raise ValueError(
                    "正常類別之外至少要有一個缺陷類別資料夾（例：scratch、void）；只有正常影像請用異常偵測任務"
                )
            normal_paths = [paths[i] for i in np.flatnonzero(labels == self.normal_class)]
            self.bank = _PatchBank.fit(
                dino,
                normal_paths,
                p,
                normal_class=self.normal_class,
                progress=lambda f: self.ctx.progress(start + span + 0.4 * span * f, "training"),
                resolved=resolved,
            )
            self.support_scores, _, self.defect_desc = self.bank.analyse(
                dino, paths, emb, progress=lambda f: self.ctx.progress(start + 1.4 * span + 0.3 * span * f, "training")
            )
        resolved["patchcore"] = want_bank
        info(f"patchcore={want_bank} ({why_bank})")

        # --- head: evaluation + final fit ---------------------------------------------------------
        head_kind, why_head = resolve_head(p.get("head", "auto"), min(counts.values()))
        self.head_kind = head_kind
        head_kw = {"k": p.get("k", "auto"), "C": float(p.get("C", 1.0))}
        self.metrics = self._evaluate(emb, labels, counts, head_kw)
        self.head = FewShotHead(self.head_kind, **head_kw).fit(emb, labels)
        self.classes, self.protos = self.head.classes, self.head.protos
        resolved.update({"head": head_kind, "k": self.head.k if head_kind == "knn" else None})
        if self.bank is not None:
            self.defect_head = self._fit_defect_head(head_kw)
        self.meta.update(
            {
                "classes": self.classes,
                "backbone": self.backbone_id,
                "finetune": self.finetune,
                "features": self.spec.to_dict(),
                "feature_dim": int(emb.shape[1]),
                "layer_report": self.layer_report,
                "support_per_class": dict(counts),
                "normal_class": self.normal_class,
                "patchcore": self.bank.meta() if self.bank else None,
                "resolved": resolved,
            }
        )
        if self.ft is not None:
            self.meta.update(
                {
                    "rank": self.ft.rank,
                    "lora_alpha": self.ft.alpha,
                    "finetune_metrics": self.ft.metrics,
                    "finetune_best_epoch": self.ft.meta.get("best_epoch"),
                    "augment": self.ft.meta.get("augment"),
                }
            )
        info(
            f"{self.family}: finetune={self.finetune} classes={len(self.classes)} support={len(labels)} "
            f"head={head_kind} ({why_head}) "
            + (f"patchcore(threshold={self.bank.threshold:.4f}) " if self.bank else "")
            + ", ".join(f"{k}={v:.4f}" for k, v in self.metrics.items())
        )

    def _fit_defect_head(self, head_kw: dict[str, Any]) -> FewShotHead | None:
        assert self.bank is not None and self.defect_desc is not None
        defect = self.labels != self.normal_class
        if defect.sum() == 0:
            return None
        return FewShotHead(self.head_kind, **head_kw).fit(self.defect_desc[defect], self.labels[defect])

    def _evaluate(
        self, emb: np.ndarray, labels: np.ndarray, counts: Counter, head_kw: dict[str, Any]
    ) -> dict[str, float]:
        if min(counts.values()) >= 2 and len(counts) >= 2:
            tr, va = holdout(len(labels), labels, "classification")
            if self.bank is not None and self.defect_desc is not None:
                preds = self._two_stage_eval(tr, va, labels, head_kw)
            else:
                preds, _, _, _ = FewShotHead(self.head_kind, **head_kw).fit(emb[tr], labels[tr]).predict(emb[va])
            return M.classification(labels[va], preds)
        preds = []  # leave-one-out with the configured head (the bank is not rebuilt per fold)
        for n in range(len(labels)):
            keep = np.arange(len(labels)) != n
            head = FewShotHead(self.head_kind, **head_kw).fit(emb[keep], labels[keep])
            preds.append(head.predict(emb[n : n + 1])[0][0])
        return M.classification(labels, preds)

    def _two_stage_eval(self, tr, va, labels, head_kw) -> list[str]:
        """Holdout estimate of the two-stage classifier: the bank's threshold (fitted on normal images, some of
        which may be in ``va``) decides normal vs. defect, a head fitted on the training defects classifies the
        rest."""
        assert self.bank is not None and self.defect_desc is not None and self.normal_class is not None
        scores = self.support_scores
        defect_tr = [i for i in tr if labels[i] != self.normal_class]
        head = (
            FewShotHead(self.head_kind, **head_kw).fit(self.defect_desc[defect_tr], labels[defect_tr])
            if len(defect_tr)
            else None
        )
        preds = []
        for i in va:
            if scores[i] <= self.bank.threshold or head is None:
                preds.append(self.normal_class)
            else:
                preds.append(head.predict(self.defect_desc[i : i + 1])[0][0])
        return preds

    def export(self, out: Path) -> list[ArtifactOut]:
        art = _save_bank(
            out,
            self.head,
            self.emb,
            self.labels,
            self.ids,
            self.meta,
            self.metrics,
            bank=self.bank,
            defect_head=self.defect_head,
            defect_desc=self.defect_desc,
        )
        if self.ft is not None:
            self.ft.save_backbone(out / "model")
        return [art]


DinoFewShotTrainer = DinoTrainer  # the family's name before fine-tuning was folded in


def _save_bank(
    out: Path,
    head: FewShotHead,
    emb: np.ndarray,
    labels: np.ndarray,
    ids: np.ndarray,
    meta: dict[str, Any],
    metrics: dict[str, float],
    *,
    bank: _PatchBank | None = None,
    defect_head: FewShotHead | None = None,
    defect_desc: np.ndarray | None = None,
    set_default: bool = False,
) -> ArtifactOut:
    import joblib

    model_dir = out / "model"
    model_dir.mkdir(parents=True, exist_ok=True)
    arrays: dict[str, np.ndarray] = {
        "classes": np.asarray(head.classes, dtype=str),
        "prototypes": np.asarray(head.protos, dtype=np.float32),
        "support": np.asarray(emb, dtype=np.float32),  # raw (uncentred) fused vectors; the head centres them
        "support_labels": np.asarray(labels, dtype=str),
        "support_ids": np.asarray(ids, dtype=str),
    }
    if bank is not None:
        arrays["normal_bank"] = bank.bank.astype(np.float16)
        if defect_desc is not None:
            arrays["defect_support"] = np.asarray(defect_desc, dtype=np.float32)
    np.savez_compressed(model_dir / "prototypes.npz", **arrays)
    heads: dict[str, Any] = {}
    if head.model is not None:
        heads["head"] = head.model
    if defect_head is not None and defect_head.model is not None:
        heads["defect_head"] = defect_head.model
    if heads:
        joblib.dump(heads, model_dir / "head.joblib")
    elif (model_dir / "head.joblib").exists():
        (model_dir / "head.joblib").unlink()
    full_meta = {
        **meta,
        **head.meta(),
        "classes": list(head.classes),
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


def _finetuned_backbone(ctx, backbone_id: str, model_path: Path, meta: dict[str, Any]):
    """Rebuild the fine-tuned backbone an artifact was trained with (``lora.pt`` adapters on the zoo weights,
    or the saved ``backbone/`` of a full fine-tune)."""
    import torch

    finetune = resolve_finetune(meta.get("finetune"))
    if finetune == "none":
        return None
    if finetune == "full":
        return _load_backbone(model_path / "backbone")
    model = _load_backbone(ctx.weight(backbone_id))
    inject_lora(model, int(meta.get("rank") or 8), float(meta.get("lora_alpha") or 16))
    _missing, unexpected = model.load_state_dict(
        torch.load(model_path / "lora.pt", map_location="cpu", weights_only=True), strict=False
    )
    if unexpected:
        raise ValueError(f"LoRA 權重與骨幹不符：{unexpected[:3]}")
    return model


def _copy_backbone_files(src: Path, dst: Path) -> None:
    if (src / "lora.pt").exists():
        shutil.copy2(src / "lora.pt", dst / "lora.pt")
    if (src / "backbone").is_dir() and not (dst / "backbone").exists():
        shutil.copytree(src / "backbone", dst / "backbone")


class DinoInferencer(BaseInferencer):
    def load(self, model_path: Path, metadata: dict[str, Any]) -> None:
        import joblib

        bank = np.load(model_path / "prototypes.npz", allow_pickle=False)
        local = model_path / "metadata.json"
        self.meta = {
            **(json.loads(local.read_text(encoding="utf-8")) if local.exists() else {}),
            **(metadata or {}),
        }
        self.support = bank["support"].astype(np.float32)
        self.support_labels = bank["support_labels"].astype(str)
        self.support_ids = bank["support_ids"].astype(str)
        self.spec = FeatureSpec.from_dict(self.meta.get("features"))
        heads = joblib.load(model_path / "head.joblib") if (model_path / "head.joblib").exists() else {}
        self.head = FewShotHead.from_meta(self.meta).fit(self.support, self.support_labels)
        if "head" in heads:
            self.head.model = heads["head"]
        self.classes, self.protos = self.head.classes, self.head.protos
        self.normal_class = self.meta.get("normal_class")
        self.bank: _PatchBank | None = None
        self.defect_head: FewShotHead | None = None
        self.defect_support: np.ndarray | None = None
        bank_meta = self.meta.get("patchcore") or self.meta.get("normal_bank")
        if bank_meta and "normal_bank" in bank.files:
            self.bank = _PatchBank.from_meta(bank_meta, bank["normal_bank"])
            self.defect_support = bank["defect_support"].astype(np.float32) if "defect_support" in bank.files else None
            defect = self.support_labels != self.normal_class
            if self.defect_support is not None and defect.any():
                self.defect_head = FewShotHead.from_meta(self.meta).fit(
                    self.defect_support[defect], self.support_labels[defect]
                )
                if "defect_head" in heads:
                    self.defect_head.model = heads["defect_head"]
        backbone_id = str(self.meta.get("backbone", "dinov2-small"))
        self.dino = _Dino(
            self.ctx, backbone_id, self.spec, model=_finetuned_backbone(self.ctx, backbone_id, model_path, self.meta)
        )
        self.model_path = model_path
        info(
            f"dino: {len(self.classes)} classes, finetune={resolve_finetune(self.meta.get('finetune'))}, "
            f"head={self.head.kind}, "
            + (f"patchcore threshold={self.bank.threshold:.4f}" if self.bank else "no patchcore")
        )

    def predict(self, ds: Dataset, mode: str, options: dict[str, Any], out: Path) -> PredictResult:
        out.mkdir(parents=True, exist_ok=True)
        ids = ds.ids or [Path(p).name for p in ds.X]
        paths = [Path(p) for p in ds.X]
        attention = bool(options.get("attention", True)) and mode in ("predict", "retrieve")
        two_stage = mode == "predict" and self.bank is not None and str(options.get("patchcore", "on")) != "off"
        if attention and not two_stage:
            emb, patches = self.dino.embed(paths, patches=True, progress=lambda f: self.ctx.progress(0.6 * f))
        else:
            emb, patches = self.dino.embed(paths, progress=lambda f: self.ctx.progress(0.6 * f)), None
        k = int(options.get("k", self.head.k))
        if mode == "extend":
            return self._extend(ds, emb, paths, out)
        if mode == "embed":
            np.save(out / "embeddings.npy", emb)
            rows = [{"id": i, "embedding": [round(float(v), 6) for v in e]} for i, e in zip(ids, emb, strict=True)]
            return PredictResult(
                rows,
                {"mode": mode, "n": len(rows), "dim": int(emb.shape[1])},
                [ArtifactOut(name="embeddings", kind="report", path="output/embeddings.npy", framework="torch")],
            )
        if mode == "retrieve":
            order = str(options.get("order", "both"))
            if order not in ("similar", "dissimilar", "both"):
                raise ValueError("order 必須是 similar / dissimilar / both")
            sims = self.head.transform(emb) @ self.head.transform(self.support).T
            rows, ref_idx = [], []
            for n, i in enumerate(ids):
                rows.append({"id": i, **_neighbour_rows(sims[n], order, k, self.support_labels, self.support_ids)})
                ref_idx.append(int(np.argmin(sims[n]) if order == "dissimilar" else np.argmax(sims[n])))
            if attention and patches is not None:
                refs = np.stack([self.dino.patch_reference(self.support[j]) for j in ref_idx])
                for row, rel in zip(
                    rows, _attention_maps(out, ids, paths, patches, refs, self.dino.processor, True), strict=False
                ):
                    row["attention"] = rel
            novel = sorted(rows, key=lambda r: r["max_similarity"])[:20]
            return PredictResult(
                rows,
                {
                    "mode": mode,
                    "n": len(rows),
                    "k": k,
                    "order": order,
                    "most_novel": [{"id": r["id"], "max_similarity": round(r["max_similarity"], 5)} for r in novel],
                },
            )
        if two_stage:
            return self._predict_two_stage(ids, paths, emb, options, out, attention)
        if self.head.kind == "knn":
            self.head.k = k
        preds, conf, proba, sims = self.head.predict(emb)
        reject = options.get("min_similarity", options.get("min_confidence"))
        rows = []
        for n, i in enumerate(ids):
            top = np.argsort(-proba[n])[:3]
            row = {
                "id": i,
                "prediction": preds[n],
                "confidence": float(conf[n]),
                "top3": [
                    {
                        "class": self.classes[j],
                        "similarity": round(float(sims[n][j]), 5),
                        "probability": round(float(proba[n][j]), 5),
                    }
                    for j in top
                ],
            }
            if reject is not None and conf[n] < float(reject):
                row["prediction"] = "unknown"
            rows.append(row)
        if attention and patches is not None:
            refs = self._explain_refs(rows, sims)
            for row, rel in zip(
                rows, _attention_maps(out, ids, paths, patches, refs, self.dino.processor, True), strict=False
            ):
                row["attention"] = rel
        counts = Counter(r["prediction"] for r in rows)
        return PredictResult(
            rows, {"mode": "predict", "n": len(rows), "class_counts": dict(counts), "head": self.head.kind}
        )

    def _explain_refs(self, rows, sims: np.ndarray) -> np.ndarray:
        """Per image, the patch-space vector the overlay scores every patch against: a linear / svm head's class
        weights (CAM: logit = mean over patches of w · patch, so w · patch is each patch's contribution), else
        the predicted class's prototype."""
        index = {c: j for j, c in enumerate(self.classes)}
        weights = self.head.class_weights()
        refs = []
        for n, r in enumerate(rows):
            j = index.get(r["prediction"], int(np.argmax(sims[n])))
            vec = weights[j] if weights is not None else self.protos[j]
            refs.append(self.dino.patch_reference(vec))
        return np.stack(refs)

    def _predict_two_stage(self, ids, paths: list[Path], emb: np.ndarray, options, out: Path, attention: bool):
        assert self.bank is not None and self.normal_class is not None
        threshold = float(options["threshold"]) if options.get("threshold") is not None else self.bank.threshold
        scores, maps, desc = self.bank.analyse(
            self.dino, paths, emb, progress=lambda f: self.ctx.progress(0.6 + 0.3 * f)
        )
        reject = options.get("min_similarity", options.get("min_confidence"))
        rows = []
        defect_rows: list[int] = []
        for n, i in enumerate(ids):
            anomalous = bool(scores[n] > threshold)
            hot = int(maps[n].argmax())
            row: dict[str, Any] = {
                "id": i,
                "prediction": self.normal_class,
                "confidence": float(np.clip(0.5 + 0.5 * (threshold - scores[n]) / (threshold + 1e-9), 0.5, 1.0)),
                "anomaly_score": float(scores[n]),
                "is_anomaly": anomalous,
                "hot_patch_row": hot // self.bank.grid,
                "hot_patch_col": hot % self.bank.grid,
            }
            if anomalous:
                defect_rows.append(n)
            rows.append(row)
        if defect_rows:
            if self.defect_head is None:
                for n in defect_rows:
                    rows[n]["prediction"] = "unknown"
                    rows[n]["confidence"] = 0.0
            else:
                preds, conf, proba, _ = self.defect_head.predict(desc[defect_rows])
                for m, n in enumerate(defect_rows):
                    top = np.argsort(-proba[m])[:3]
                    rows[n]["prediction"] = preds[m]
                    rows[n]["confidence"] = float(conf[m])
                    rows[n]["top3"] = [
                        {"class": self.defect_head.classes[j], "probability": round(float(proba[m][j]), 5)} for j in top
                    ]
                    if reject is not None and conf[m] < float(reject):
                        rows[n]["prediction"] = "unknown"
        if attention:
            for row, rel in zip(
                rows, _overlays(out, ids, paths, [np.asarray(m) for m in maps], self.dino.processor), strict=False
            ):
                row["attention"] = rel
        counts = Counter(r["prediction"] for r in rows)
        return PredictResult(
            rows,
            {
                "mode": "predict",
                "n": len(rows),
                "class_counts": dict(counts),
                "head": self.head.kind,
                "normal_class": self.normal_class,
                "threshold": threshold,
                "score_agg": self.bank.score_agg,
                "flagged": len(defect_rows),
            },
        )

    def _extend(self, ds: Dataset, emb: np.ndarray, paths: list[Path], out: Path) -> PredictResult:
        """Add new classes (bin codes) or more examples without retraining the backbone: the support set grows,
        the heads are re-fitted on the cached features (seconds), the PatchCore bank gains the new normal
        images' patches and the defect head the new defects' descriptors."""
        if not ds.has_labels:
            raise ValueError("extend 需要以類別命名的資料夾（新 bin code 的範例影像）")
        labels = np.asarray(ds.y).astype(str)
        new_ids = np.asarray(ds.ids).astype(str)
        all_emb = np.concatenate([self.support, emb])
        all_labels = np.concatenate([self.support_labels, labels])
        all_ids = np.concatenate([self.support_ids, new_ids])
        head = FewShotHead.from_meta(self.meta).fit(all_emb, all_labels)
        added = sorted(set(labels.tolist()) - set(self.classes))
        meta = {k: v for k, v in self.meta.items() if k not in ("metrics", "classes", "inference_modes")}
        meta["support_per_class"] = dict(Counter(all_labels.tolist()))
        defect_head, defect_desc = None, None
        if self.bank is not None and self.normal_class is not None:
            _scores, _, desc = self.bank.analyse(self.dino, paths, emb)
            new_normal = labels == self.normal_class
            if new_normal.any():
                _, patches = self.dino.embed([p for p, n in zip(paths, new_normal, strict=True) if n], patches=True)
                patches = _project(patches, self.bank.proj)
                extra = _coreset(patches.reshape(-1, patches.shape[-1]), self.bank.coreset_ratio)
                self.bank.bank = np.concatenate([self.bank.bank, extra])
                self.bank._bank_t = None
            defect_desc = np.concatenate([self.defect_support, desc]) if self.defect_support is not None else desc
            defect = all_labels != self.normal_class
            if defect.any():
                defect_head = FewShotHead.from_meta(self.meta).fit(defect_desc[defect], all_labels[defect])
            meta["patchcore"] = self.bank.meta()
        art = _save_bank(
            out.parent,
            head,
            all_emb,
            all_labels,
            all_ids,
            meta,
            self.meta.get("metrics") or {},
            bank=self.bank,
            defect_head=defect_head,
            defect_desc=defect_desc,
            set_default=True,
        )
        _copy_backbone_files(self.model_path, out.parent / "model")  # a fine-tuned backbone travels with the bank
        info(f"extend: +{len(labels)} examples, new classes={added}, total classes={len(head.classes)}")
        rows = [{"id": i, "label": lbl, "status": "added"} for i, lbl in zip(new_ids, labels, strict=True)]
        return PredictResult(
            rows,
            {"mode": "extend", "added_examples": len(labels), "new_classes": added, "classes": head.classes},
            [art],
        )


# --- anomaly detection (PatchCore) ------------------------------------------------------------------------


class DinoPatchCoreTrainer(BaseTrainer):
    """PatchCore on frozen DINO patch tokens (normal images only). ``layers`` last / cross / list,
    ``neighborhood`` 1 / 3, ``score_agg`` auto / max / top1, ``coreset_ratio`` auto, ``bank_augment`` auto."""

    framework = "torch"
    inference_modes = ["score", "embed"]

    def fit(self, ds: Dataset) -> None:
        p = self.params
        self.backbone_id = str(p.get("backbone", "dinov2-small"))
        spec = FeatureSpec.from_params(p)
        if spec.layers == "auto":
            raise ValueError("PatchCore 沒有標籤可挑層，layers 請用 last / cross 或層數列表")
        dino = _Dino(self.ctx, self.backbone_id, spec)
        self.spec = dino.spec
        paths = [Path(x) for x in ds.X]
        y = _binary_anomaly_labels(ds.y) if ds.has_labels else None
        normal_idx = np.flatnonzero(y == 0) if y is not None else np.arange(len(paths))
        if len(normal_idx) == 0:
            raise ValueError("需要正常（good / normal）影像來建立記憶庫")
        resolved: dict[str, Any] = {"layers": list(dino.layers)}
        self.bank = _PatchBank.fit(
            dino,
            [paths[i] for i in normal_idx],
            p,
            progress=lambda f: self.ctx.progress(0.05 + 0.7 * f, "training"),
            resolved=resolved,
        )
        # validation: every anomalous image (never in the bank) + the held-out normals are inside the normal set
        # the bank was built from only partially, so the score of the normals is optimistic; the anomalies decide
        val_idx = np.flatnonzero(y == 1) if y is not None else np.array([], dtype=int)
        hold = [paths[i] for i in normal_idx[: max(1, len(normal_idx) // 5)]]
        scores_n, _ = self.bank.score(dino, hold, progress=lambda f: self.ctx.progress(0.75 + 0.1 * f, "training"))
        if len(val_idx):
            scores_a, _ = self.bank.score(
                dino, [paths[i] for i in val_idx], progress=lambda f: self.ctx.progress(0.85 + 0.1 * f, "training")
            )
            val_scores = np.concatenate([scores_n, scores_a])
            labels = np.concatenate([np.zeros(len(scores_n), int), np.ones(len(scores_a), int)])
        else:
            val_scores, labels = scores_n, None
        self.metrics = M.anomaly(val_scores, labels, self.bank.threshold)
        self.meta.update(
            {
                "backbone": self.backbone_id,
                "features": self.spec.to_dict(),
                "patchcore": self.bank.meta(),
                "threshold": self.bank.threshold,
                "grid": self.bank.grid,
                "k": self.bank.k,
                "resolved": resolved,
            }
        )
        info(f"{self.family}: " + ", ".join(f"{k}={v:.4f}" for k, v in self.metrics.items()))

    def export(self, out: Path) -> list[ArtifactOut]:
        model_dir = out / "model"
        model_dir.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(model_dir / "memory_bank.npz", bank=self.bank.bank)
        meta = {**self.meta, "metrics": self.metrics}
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


class DinoPatchCoreInferencer(BaseInferencer):
    def load(self, model_path: Path, metadata: dict[str, Any]) -> None:
        bank = np.load(model_path / "memory_bank.npz", allow_pickle=False)["bank"]
        local = model_path / "metadata.json"
        self.meta = {
            **(json.loads(local.read_text(encoding="utf-8")) if local.exists() else {}),
            **(metadata or {}),
        }
        self.spec = FeatureSpec.from_dict(self.meta.get("features") or {"layers": "last"})
        self.dino = _Dino(self.ctx, str(self.meta.get("backbone", "dinov2-small")), self.spec)
        bank_meta = self.meta.get("patchcore") or {
            "threshold": self.meta.get("threshold") or 0.0,
            "grid": self.meta.get("grid") or 16,
            "k": self.meta.get("k") or 3,
            "projection": self.meta.get("projection"),
        }
        self.bank = _PatchBank.from_meta(bank_meta, bank)

    def predict(self, ds: Dataset, mode: str, options: dict[str, Any], out: Path) -> PredictResult:
        out.mkdir(parents=True, exist_ok=True)
        ids = ds.ids or [Path(p).name for p in ds.X]
        paths = [Path(p) for p in ds.X]
        if mode == "embed":
            emb = self.dino.embed(paths, progress=self.ctx.progress)
            np.save(out / "embeddings.npy", emb)
            rows = [{"id": i, "embedding": [round(float(v), 6) for v in e]} for i, e in zip(ids, emb, strict=True)]
            return PredictResult(
                rows,
                {"mode": mode, "n": len(rows)},
                [ArtifactOut(name="embeddings", kind="report", path="output/embeddings.npy", framework="torch")],
            )
        if options.get("k"):
            self.bank.k = int(options["k"])
        scores, maps = self.bank.score(self.dino, paths, progress=lambda f: self.ctx.progress(0.9 * f))
        override = options.get("threshold")
        threshold = float(override) if override is not None else float(self.bank.threshold or np.percentile(scores, 99))
        grid = self.bank.grid or round(np.sqrt(len(maps[0])))
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
        if save_heat:
            for row, rel in zip(
                rows, _overlays(out, ids, paths, [np.asarray(m) for m in maps], self.dino.processor), strict=False
            ):
                row["attention"] = rel
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
                "score_agg": self.bank.score_agg,
                "most_anomalous": [{"id": r["id"], "anomaly_score": r["anomaly_score"]} for r in ranked],
            },
            extra,
        )


def _heatmap_name(image_id: Any, seen: set[str]) -> str:
    """See ``viz.overlay_name`` (``a/x.jpg`` → ``a__x.png``, ties broken with a counter)."""
    from trainer import viz

    return viz.overlay_name(image_id, seen)


def _save_heatmap(heat_dir: Path, name: str, grid: np.ndarray, threshold: float) -> str:
    from PIL import Image

    heat_dir.mkdir(parents=True, exist_ok=True)
    norm = np.clip(grid / max(threshold * 1.5, 1e-6), 0, 1)
    img = Image.fromarray((norm * 255).astype(np.uint8), mode="L").resize((224, 224), Image.BILINEAR)
    img.save(heat_dir / name)
    return f"heatmaps/{name}"


DinoFewShotInferencer = DinoInferencer


__all__ = [
    "DinoFewShotInferencer",
    "DinoFewShotTrainer",
    "DinoFinetuneInferencer",
    "DinoFinetuneTrainer",
    "DinoInferencer",
    "DinoPatchCoreInferencer",
    "DinoPatchCoreTrainer",
    "DinoTrainer",
    "YoloInferencer",
    "YoloTrainer",
    "all_images",
]


# ---------------------------------------------------------------------------------------------------
# DINOv2 / v3 LoRA fine-tuning — low-rank adapters on the attention projections + a linear head
# ---------------------------------------------------------------------------------------------------

# transformers ≥ 5 names the DINOv2 projections q_proj / k_proj / v_proj; 4.x used query / key / value
LORA_TARGETS = ("q_proj", "k_proj", "v_proj", "query", "key", "value")
FINETUNE_STEPS = 400  # epochs=auto: enough epochs for about this many optimiser steps
FINETUNE_EPOCHS = (5, 40)  # epochs=auto bounds
FINETUNE_BATCH = {224: 16, 336: 8, 448: 4}  # batch=auto by image size (VRAM)


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


AUGMENT_OPS = ("hflip", "vflip", "rotate90", "crop", "brightness", "contrast")
DEFAULT_AUGMENT = ("crop", "hflip")  # safe for industrial images: no orientation change, no colour shift


def parse_augment(value: Any) -> tuple[str, ...]:
    """``augment`` param → the ops to apply at train time. ``true`` / ``default`` = crop + hflip (the family
    default), ``false`` / ``none`` / empty = none, a list or comma string picks from AUGMENT_OPS."""
    if value is None or value is False:
        return ()
    if value is True:
        return DEFAULT_AUGMENT
    if isinstance(value, str) and value.strip().lower() == "default":
        return DEFAULT_AUGMENT
    if isinstance(value, str) and value.strip().lower() in ("none", "false", "off"):
        return ()
    items = value.split(",") if isinstance(value, str) else list(value)
    ops = tuple(str(v).strip().lower() for v in items if str(v).strip())
    bad = [o for o in ops if o not in AUGMENT_OPS]
    if bad:
        raise ValueError(f"augment 不認得 {bad}，可用：{', '.join(AUGMENT_OPS)}")
    return ops


_AUG_RNG = np.random.default_rng()


def augment_image(im, ops: tuple[str, ...], rng: np.random.Generator | None = None):
    """Random train-time augmentation on a PIL image (each op fires with p=0.5, crop keeps 80–100% of the frame)."""
    from PIL import ImageEnhance, ImageOps

    rng = rng or _AUG_RNG
    for op in ops:
        if rng.random() >= 0.5:
            continue
        if op == "hflip":
            im = ImageOps.mirror(im)
        elif op == "vflip":
            im = ImageOps.flip(im)
        elif op == "rotate90":
            im = im.rotate(90 * int(rng.integers(1, 4)), expand=True)
        elif op == "crop":
            w, h = im.size
            f = float(rng.uniform(0.8, 1.0))
            cw, ch = max(1, int(w * f)), max(1, int(h * f))
            x0, y0 = int(rng.integers(0, w - cw + 1)), int(rng.integers(0, h - ch + 1))
            im = im.crop((x0, y0, x0 + cw, y0 + ch))
        elif op == "brightness":
            im = ImageEnhance.Brightness(im).enhance(float(rng.uniform(0.8, 1.2)))
        elif op == "contrast":
            im = ImageEnhance.Contrast(im).enhance(float(rng.uniform(0.8, 1.2)))
    return im


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


def resolve_epochs(value: Any, n_train: int, batch: int) -> tuple[int, str]:
    if value in (None, "", "auto"):
        steps_per_epoch = max(1, int(np.ceil(n_train / batch)))
        e = int(np.clip(int(np.ceil(FINETUNE_STEPS / steps_per_epoch)), *FINETUNE_EPOCHS))
        return e, f"{n_train} images / batch {batch} → {e} epochs ≈ {FINETUNE_STEPS} steps"
    return int(value), "chosen by the user"


def resolve_batch(value: Any, image_size: int | None) -> tuple[int, str]:
    if value in (None, "", "auto"):
        size = int(image_size or 224)
        b = FINETUNE_BATCH.get(size, 16 if size <= 224 else 8 if size <= 336 else 4)
        return b, f"image_size {size} → batch {b}"
    return int(value), "chosen by the user"


class _DinoFinetuneNet:
    """Backbone (from the zoo) + linear head shared by the trainer and the inferencer. The same FeatureSpec as
    the frozen encoder decides which layers feed the head (patch tokens only, mean per layer, layers
    concatenated, L2-normalised), so the LoRA adapters train on the same features the frozen family uses and
    the head's weights double as a class activation map (logit = mean over patches of w · patch)."""

    def __init__(
        self,
        ctx,
        backbone_id: str,
        method: str,
        n_classes: int,
        rank: int,
        alpha: float,
        backbone_dir=None,
        spec: FeatureSpec | None = None,
        legacy_head: bool = False,
    ):
        import torch
        from transformers import AutoImageProcessor

        spec = spec or FeatureSpec()
        zoo_path = ctx.weight(backbone_id)
        self.torch = torch
        self.ctx = ctx
        self.method = method
        self.processor = AutoImageProcessor.from_pretrained(str(zoo_path), local_files_only=True)
        _set_image_size(self.processor, spec.image_size)
        src = backbone_dir if backbone_dir is not None else zoo_path
        self.backbone = _load_backbone(Path(src))
        self.lora_layers = 0
        if method == "lora":
            self.lora_layers = inject_lora(self.backbone, rank, alpha)
        if method != "full":
            for name, p in self.backbone.named_parameters():
                p.requires_grad_(".lora_" in name)
        cfg = self.backbone.config
        self.kind = backbone_kind(backbone_id, getattr(cfg, "model_type", None))
        self.n_layers = int(cfg.num_hidden_layers)
        self.hidden = int(cfg.hidden_size)
        self.final_norm = _final_norm(self.backbone)
        if spec.layers == "auto":
            raise ValueError("微調不支援 layers=auto（沒有凍結的支援集可以挑層）；請用 last / cross 或層數列表")
        self.layers = resolve_layers(spec.layers, self.n_layers, self.kind)
        self.spec = replace(spec, layers=self.layers)
        dim = self.hidden * len(self.layers)
        self.legacy_head = legacy_head
        self.head = (
            torch.nn.Sequential(torch.nn.LayerNorm(dim), torch.nn.Linear(dim, n_classes))
            if legacy_head
            else torch.nn.Linear(dim, n_classes)
        )
        self.backbone.to(ctx.device)
        self.head.to(ctx.device)
        self.feature_dim = dim
        self.n_special = 1 + special_tokens(cfg)

    def pixels(self, paths: list[Path], augment: tuple[str, ...] = ()):
        from PIL import Image

        imgs = []
        for p in paths:
            im = Image.open(p).convert("RGB")
            if augment:
                im = augment_image(im, augment)
            imgs.append(im)
        return self.processor(images=imgs, return_tensors="pt")["pixel_values"].to(self.ctx.device)

    def _tokens(self, px):
        """Patch tokens per selected layer (final norm applied; gradients flow when the adapters train)."""
        hs = self.backbone(pixel_values=px, output_hidden_states=True).hidden_states
        toks = []
        for layer in self.layers:
            h = self.final_norm(hs[layer]) if self.final_norm is not None else hs[layer]
            toks.append(h[:, self.n_special :])
        return toks

    def _fuse(self, tok_list):
        nf = self.torch.nn.functional.normalize
        return nf(self.torch.cat([nf(t.mean(dim=1), dim=-1) for t in tok_list], dim=1), dim=-1)

    def features(self, px):
        return self._fuse(self._tokens(px))

    def tokens(self, px):
        """(features, L2-normalised fused patch grid) for one batch, no gradient."""
        with self.torch.no_grad():
            toks = self._tokens(px)
            return self._fuse(toks), fuse_tokens(toks)

    def cam(self, px, target: np.ndarray) -> np.ndarray:
        """Class activation map on the patch grid: w[target] · patch for every patch (B, L). Exact up to a
        positive scale for a linear head on mean-pooled, per-layer-normalised tokens; no gradients needed."""
        torch = self.torch
        self.train_mode(False)
        with torch.no_grad():
            _, grid = self.tokens(px)
            linear = self.head[-1] if self.legacy_head else self.head
            w = linear.weight[torch.as_tensor(target, device=grid.device).long()]  # (B, Dp)
            cam = (grid * w[:, None, :]).sum(dim=-1).clamp(min=0)
        return cam.cpu().numpy()

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
                out.append(self.features(self.pixels(paths[k : k + batch])).cpu().numpy())
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

    def patch_reference(self, vec: np.ndarray) -> np.ndarray:
        return patch_reference(vec, self.hidden, len(self.layers))


class DinoFinetuneTrainer(BaseTrainer):
    """Supervised LoRA fine-tuning of DINOv2 / v3 for image classification: low-rank adapters on the attention
    projections train together with a linear head (the base weights stay untouched; artifact = adapters +
    head, a few MB). The feature options (``layers`` / ``image_size``) are the same as the frozen family;
    ``epochs`` / ``batch`` default to ``auto`` (data size / image size). Pretrained weights always come from the
    zoo (``ctx.weight``)."""

    framework = "torch"
    inference_modes = ["predict", "embed", "retrieve"]

    def fit(self, ds: Dataset) -> None:
        import torch

        if not ds.has_labels:
            raise ValueError("分類微調需要以類別命名的資料夾")
        p = self.params
        self.backbone_id = str(p.get("backbone", "dinov2-small"))
        self.method = str(p.get("method", "lora"))
        if self.method not in ("lora", "full"):
            raise ValueError("微調只提供 lora / full（線性探針 = finetune=none + head=linear）")
        self.rank = int(p.get("rank", 8))
        self.alpha = float(p.get("lora_alpha", 2 * self.rank))
        spec = FeatureSpec.from_params(p)
        batch, why_batch = resolve_batch(p.get("batch", "auto"), spec.image_size)
        lr = float(p.get("lr", 1e-3))
        self.backbone_lr = float(p.get("backbone_lr", 1e-5))  # full fine-tune: the pretrained weights move slowly
        augment = parse_augment(p.get("augment", DEFAULT_AUGMENT))
        torch.manual_seed(int(p.get("seed", 42)))
        np.random.seed(int(p.get("seed", 42)))

        paths = [Path(x) for x in ds.X]
        labels = np.asarray(ds.y).astype(str)
        self.classes = sorted(set(labels.tolist()))
        index = {c: i for i, c in enumerate(self.classes)}
        y = np.array([index[v] for v in labels])
        tr, va = holdout(len(paths), labels, "classification")
        epochs, why_epochs = resolve_epochs(p.get("epochs", "auto"), len(tr), batch)
        self.net = _DinoFinetuneNet(
            self.ctx, self.backbone_id, self.method, len(self.classes), self.rank, self.alpha, spec=spec
        )
        bb_params, _head_params = self.net.trainable_parameters()
        n_bb = sum(int(q.numel()) for q in bb_params)
        info(
            f"{self.family}: backbone={self.backbone_id} finetune={self.method} rank={self.rank} "
            f"classes={len(self.classes)} "
            f"train={len(tr)} val={len(va)} trainable backbone params={n_bb} (lora layers={self.net.lora_layers}) "
            f"augment={list(augment) or 'none'} {self.net.spec.describe()} feature dim={self.net.feature_dim} "
            f"epochs={epochs} ({why_epochs}) batch={batch} ({why_batch}) lr={lr:g} device={self.ctx.device}"
        )
        self.ctx.progress(0.02, "training")

        best: tuple[float, dict[str, Any], dict[str, Any], int] | None = None
        for attempt in range(2):
            try:
                best = self._train(paths, y, tr, va, epochs, batch, lr, augment)
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
                "rank": self.rank,
                "lora_alpha": self.alpha,
                "feature_dim": self.net.feature_dim,
                "features": self.net.spec.to_dict(),
                "head": "linear",
                "augment": list(augment),
                "best_epoch": best_epoch,
                "batch": batch,
                "train_per_class": dict(Counter(labels[tr].tolist())),
                "resolved": {
                    "layers": list(self.net.layers),
                    "epochs": epochs,
                    "batch": batch,
                    "lr": lr,
                    **({"backbone_lr": self.backbone_lr} if self.method == "full" else {}),
                },
            }
        )
        info(f"{self.family}: best epoch {best_epoch} " + ", ".join(f"{k}={v:.4f}" for k, v in self.metrics.items()))

    def _train(self, paths, y, tr, va, epochs, batch, lr, augment):
        import torch

        net = self.net
        bb_params, head_params = net.trainable_parameters()
        groups = [{"params": head_params, "lr": lr}]
        if bb_params:
            groups.append({"params": bb_params, "lr": self.backbone_lr if self.method == "full" else lr})
        opt = torch.optim.AdamW(groups, weight_decay=float(self.params.get("weight_decay", 0.01)))
        steps = epochs * max(1, int(np.ceil(len(tr) / batch)))
        sched = torch.optim.lr_scheduler.LambdaLR(
            opt, lambda s: min(1.0, (s + 1) / max(1, int(0.1 * steps))) * max(0.05, 1 - s / steps)
        )
        loss_fn = torch.nn.CrossEntropyLoss(label_smoothing=0.05)
        rng = np.random.default_rng(0)
        best = None
        for epoch in range(1, epochs + 1):
            net.train_mode(True)
            order = rng.permutation(tr)
            total = 0.0
            for s in range(0, len(order), batch):
                idx = order[s : s + batch]
                yb = torch.as_tensor(y[idx]).to(self.ctx.device)
                logits = net.head(net.features(net.pixels([paths[i] for i in idx], augment=augment)))
                loss = loss_fn(logits, yb)
                opt.zero_grad(set_to_none=True)
                loss.backward()
                torch.nn.utils.clip_grad_norm_(head_params + bb_params, 1.0)
                opt.step()
                sched.step()
                total += float(loss.detach()) * len(idx)
                self.ctx.progress(0.02 + 0.9 * ((epoch - 1) + (s + len(idx)) / len(order)) / epochs, "training")
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
                )
                best = (score, head_state, bb_state, epoch)
            self.ctx.epoch(epoch, ep)
        assert best is not None
        self.metrics = {k: v for k, v in self.metrics.items()}
        return best

    def save_backbone(self, model_dir: Path) -> None:
        """``lora.pt`` (adapters only, a few MB) or ``backbone/`` (a full fine-tune: the whole backbone)."""
        import torch

        model_dir.mkdir(parents=True, exist_ok=True)
        if self.method == "lora":
            torch.save(lora_state(self.net.backbone), model_dir / "lora.pt")
        else:
            self.net.backbone.save_pretrained(model_dir / "backbone")

    def export(self, out: Path) -> list[ArtifactOut]:
        import torch

        model_dir = out / "model"
        model_dir.mkdir(parents=True, exist_ok=True)
        torch.save(self.net.head.state_dict(), model_dir / "head.pt")
        self.save_backbone(model_dir)
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
        head_state = torch.load(model_path / "head.pt", map_location="cpu", weights_only=True)
        legacy = any(k.startswith("0.") or k.startswith("1.") for k in head_state)  # LayerNorm + Linear (older)
        self.net = _DinoFinetuneNet(
            self.ctx,
            str(self.meta.get("backbone", "dinov2-small")),
            method,
            len(self.classes),
            int(self.meta.get("rank") or 8),
            float(self.meta.get("lora_alpha") or 16),
            backbone_dir=model_path / "backbone" if method == "full" else None,
            spec=FeatureSpec.from_dict(self.meta.get("features")),
            legacy_head=legacy,
        )
        if method == "lora":
            _missing, unexpected = self.net.backbone.load_state_dict(
                torch.load(model_path / "lora.pt", map_location="cpu", weights_only=True), strict=False
            )
            if unexpected:
                raise ValueError(f"LoRA 權重與骨幹不符：{unexpected[:3]}")
        self.net.head.load_state_dict(head_state)
        self.net.head.to(self.ctx.device)
        ref = model_path / "reference.npz"
        if ref.exists():
            bank = np.load(ref, allow_pickle=False)
            self.ref_emb, self.ref_labels, self.ref_ids = bank["embeddings"], bank["labels"], bank["ids"]
        else:
            self.ref_emb = None
        self.batch = int(self.meta.get("batch", 16))
        info(f"dino_finetune: loaded {method} head for {len(self.classes)} classes ({self.net.spec.describe()})")

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
        attention = bool(options.get("attention", True))
        if mode == "retrieve":
            if self.ref_emb is None:
                raise ValueError("這個模型沒有參考影像庫，無法 retrieve")
            k = int(options.get("k", 5))
            order = str(options.get("order", "similar"))
            if order not in ("similar", "dissimilar", "both"):
                raise ValueError("order 必須是 similar / dissimilar / both")
            emb, patches = self._embed_with_patches(paths, batch, want_patches=attention)
            sims = emb @ self.ref_emb.T
            rows, ref_idx = [], []
            for n, i in enumerate(ids):
                rows.append({"id": i, **_neighbour_rows(sims[n], order, k, self.ref_labels, self.ref_ids)})
                ref_idx.append(int(np.argmin(sims[n]) if order == "dissimilar" else np.argmax(sims[n])))
            if attention and patches is not None:
                refs = np.stack([self.net.patch_reference(self.ref_emb[j]) for j in ref_idx])
                for row, rel in zip(
                    rows, _attention_maps(out, ids, paths, patches, refs, self.net.processor, True), strict=False
                ):
                    row["attention"] = rel
            return PredictResult(rows, {"mode": mode, "n": len(rows), "k": k, "order": order})
        proba = self.net.predict_proba(paths, batch, progress=lambda f: self.ctx.progress(0.8 * f))
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
        if attention:
            self._cam_maps(out, ids, paths, proba.argmax(axis=1), batch, rows)
        counts = Counter(r["prediction"] for r in rows)
        return PredictResult(rows, {"mode": "predict", "n": len(rows), "class_counts": dict(counts)})

    def _embed_with_patches(self, paths: list[Path], batch: int, want_patches: bool):
        """Normalised fused embeddings and (optionally) the L2-normalised fused patch grid, batch by batch."""
        embs, toks = [], []
        for k in range(0, len(paths), batch):
            feat, tok = self.net.tokens(self.net.pixels(paths[k : k + batch]))
            embs.append(feat.cpu().numpy())
            if want_patches:
                toks.append(tok.cpu().numpy().astype(np.float16))
            self.ctx.progress(0.8 * min(1.0, (k + batch) / max(1, len(paths))))
        emb = np.concatenate(embs) if embs else np.zeros((0, self.net.feature_dim), np.float32)
        return emb, (np.concatenate(toks) if toks else None)

    def _cam_maps(self, out: Path, ids, paths: list[Path], target: np.ndarray, batch: int, rows) -> None:
        values: list[np.ndarray] = []
        limit = min(len(paths), ATTENTION_MAX)
        for k in range(0, limit, batch):
            chunk = paths[k : k + batch]
            values.extend(list(self.net.cam(self.net.pixels(chunk), target[k : k + batch])))
        for row, rel in zip(
            rows[:limit], _overlays(out, ids[:limit], paths[:limit], values, self.net.processor), strict=False
        ):
            row["attention"] = rel
