"""family id → (module, TrainerClass, InferencerClass). Ids must match backend/app/catalog/model_catalog.yaml.

Modules are imported lazily so the sklearn-only environment (dev, CI) never imports torch / ultralytics.
"""

from __future__ import annotations

import importlib
from typing import Any

from trainer.models.base import BaseInferencer, BaseTrainer, Context

FAMILIES: dict[str, tuple[str, str, str]] = {
    "tabular.linear": ("trainer.models.tabular", "TabularTrainer", "TabularInferencer"),
    "tabular.svm": ("trainer.models.tabular", "TabularTrainer", "TabularInferencer"),
    "tabular.random_forest": ("trainer.models.tabular", "TabularTrainer", "TabularInferencer"),
    "tabular.xgboost": ("trainer.models.tabular", "TabularTrainer", "TabularInferencer"),
    "tabular.catboost": ("trainer.models.tabular", "TabularTrainer", "TabularInferencer"),
    "tabular.tabpfn": ("trainer.models.tabular", "TabularTrainer", "TabularInferencer"),
    "tabular.isolation_forest": ("trainer.models.tabular", "TabularTrainer", "TabularInferencer"),
    "vision.yolo": ("trainer.models.vision", "YoloTrainer", "YoloInferencer"),
    "vision.dino": ("trainer.models.vision", "DinoTrainer", "DinoInferencer"),
    # ids from before fine-tuning was folded into vision.dino (deprecated in the catalog: inference only)
    "vision.dino_fewshot": ("trainer.models.vision", "DinoTrainer", "DinoInferencer"),
    "vision.dino_finetune": ("trainer.models.vision", "DinoFinetuneTrainer", "DinoFinetuneInferencer"),
    "vision.dino_patchcore": (
        "trainer.models.vision",
        "DinoPatchCoreTrainer",
        "DinoPatchCoreInferencer",
    ),
    "vision.image_quality": ("trainer.models.iqa", "ImageQualityTrainer", "ImageQualityInferencer"),
    "sequence.patch_autoencoder": (
        "trainer.models.sequence",
        "PatchAutoencoderTrainer",
        "PatchAutoencoderInferencer",
    ),
    "spectrum.masked_autoencoder": (
        "trainer.models.sequence",
        "SpectrumMAETrainer",
        "SpectrumMAEInferencer",
    ),
    "spectrum.pls": ("trainer.models.spectrum", "PLSTrainer", "PLSInferencer"),
    "text.bert_classifier": (
        "trainer.models.text",
        "BertClassifierTrainer",
        "BertClassifierInferencer",
    ),
    "text.qwen_embedding": (
        "trainer.models.text",
        "QwenEmbeddingTrainer",
        "QwenEmbeddingInferencer",
    ),
}


# third-party packages a family needs at runtime (checked by `python -m trainer check`)
REQUIRES: dict[str, list[str]] = {
    "tabular.xgboost": ["xgboost"],
    "tabular.catboost": ["catboost"],
    "tabular.tabpfn": ["torch", "tabpfn"],
    "vision.yolo": ["torch", "ultralytics"],
    "vision.dino": ["torch", "transformers", "PIL"],
    "vision.dino_fewshot": ["torch", "transformers", "PIL"],
    "vision.dino_finetune": ["torch", "transformers", "PIL"],
    "vision.dino_patchcore": ["torch", "transformers", "PIL"],
    "sequence.patch_autoencoder": ["torch"],
    "spectrum.masked_autoencoder": ["torch"],
    "text.bert_classifier": ["torch", "transformers"],
    "text.qwen_embedding": ["torch", "transformers"],
}


def ids() -> list[str]:
    return list(FAMILIES)


def missing_packages(fid: str) -> list[str]:
    out = []
    for name in REQUIRES.get(fid, []):
        try:
            importlib.import_module(name)
        except ImportError:
            out.append(name)
    return out


def _load(fid: str, which: int) -> type:
    if fid not in FAMILIES:
        raise KeyError(f"unknown model family: {fid}")
    module, trainer_name, inferencer_name = FAMILIES[fid]
    try:
        mod = importlib.import_module(module)
    except ImportError as e:  # torch / ultralytics / transformers missing in this image
        raise RuntimeError(f"{fid} needs the deep-learning trainer image ({e.name} is not installed)") from e
    return getattr(mod, trainer_name if which == 0 else inferencer_name)


def create_trainer(fid: str, task: str | None, params: dict[str, Any], ctx: Context) -> BaseTrainer:
    return _load(fid, 0)(fid, task, params, ctx)


def create_inferencer(fid: str, ctx: Context) -> BaseInferencer:
    return _load(fid, 1)(fid, ctx)
