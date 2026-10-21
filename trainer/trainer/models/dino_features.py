"""Feature generation shared by the DINO families (frozen few-shot / PatchCore, LoRA fine-tune) and the image
analysis tool.

The pipeline is deliberately small: pick the transformer layers to read (``last`` or the ``cross`` preset),
use the patch tokens only (no CLS), average them per layer for an image-level vector, concatenate the layers
along the feature axis, L2-normalise. Heads sit on top of that vector; PatchCore sits on the per-patch grid.
Everything here is numpy except the two token helpers, so the backend tests and the analysis tool can import
it without a GPU.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

# ``cross`` = the three blocks at 9/12, 10/12 and 11/12 of the depth (9, 10, 11 on a 12-layer ViT-S / B;
# 18, 20, 22 on a 24-layer ViT-L). ``last`` = the final block only.
CROSS_FRACTIONS = (9 / 12, 10 / 12, 11 / 12)
LAYER_CHOICES = ("last", "cross", "all", "auto")
IMAGE_SIZES = (224, 336, 448)
AUTO_MAX_LAYERS = 3
COSINE_TEMPERATURE = 0.1  # softmax(sims / T) turns cosine similarities into prototype probabilities
NEIGHBORHOODS = (1, 3)
SCORE_AGGS = ("max", "top1")


def backbone_kind(backbone_id: str, model_type: str | None = None) -> str:
    """``dinov3`` when the weights / config say so, else ``dinov2``."""
    text = f"{backbone_id} {model_type or ''}".lower()
    return "dinov3" if "dinov3" in text else "dinov2"


def cross_layers(n_layers: int) -> tuple[int, ...]:
    return tuple(sorted({max(1, min(n_layers, round(f * n_layers))) for f in CROSS_FRACTIONS}))


def resolve_layers(value: Any, n_layers: int, kind: str = "dinov2") -> tuple[int, ...]:
    """``layers`` param → 1-based layer indices to read. ``last`` = the final block, ``cross`` = the preset
    scaled to this backbone's depth, ``all`` = every block (also what ``auto`` reads before it picks), a list
    or comma string is used as-is (negative = from the end)."""
    del kind  # the presets are depth-based; kept for call-site symmetry with backbone_kind()
    if n_layers < 1:
        raise ValueError("backbone has no layers")
    if value is None or value == "" or value == "last":
        return (n_layers,)
    if isinstance(value, str) and value.strip().lower() in ("all", "auto"):
        return tuple(range(1, n_layers + 1))
    if isinstance(value, str) and value.strip().lower() == "cross":
        return cross_layers(n_layers)
    items = value.split(",") if isinstance(value, str) else list(value) if isinstance(value, (list, tuple)) else [value]
    out: list[int] = []
    for item in items:
        s = str(item).strip()
        if not s:
            continue
        try:
            k = int(s)
        except ValueError as e:
            raise ValueError(f"layers 不認得 {s!r}：可用 last / cross 或層數列表（例：9,10,11）") from e
        if k < 0:
            k = n_layers + 1 + k
        if not 1 <= k <= n_layers:
            raise ValueError(f"layers {item} 超出範圍（這個骨幹有 {n_layers} 層）")
        if k not in out:
            out.append(k)
    if not out:
        return (n_layers,)
    return tuple(sorted(out))


@dataclass(frozen=True)
class FeatureSpec:
    """How one image becomes one vector (and one patch grid)."""

    layers: Any = "cross"  # "last" / "cross" / "auto" / a tuple of 1-based layer indices
    image_size: int | None = None
    neighborhood: int = 1  # PatchCore-style local aggregation of the patch grid (1 = off, 3 = 3×3 mean)

    @classmethod
    def from_params(cls, p: dict[str, Any], **overrides: Any) -> FeatureSpec:
        src = {**p, **overrides}
        layers = src.get("layers", "cross")
        if isinstance(layers, (list, tuple)):
            layers = tuple(int(v) for v in layers)
        elif layers is not None and not isinstance(layers, str):
            layers = (int(layers),)
        elif isinstance(layers, str):
            layers = layers.strip().lower() or "cross"
            if layers not in LAYER_CHOICES and not any(ch.isdigit() for ch in layers):
                raise ValueError(f"layers 不認得 {layers!r}，可用：last / cross 或層數列表（例：9,10,11）")
        image_size = src.get("image_size")
        image_size = int(image_size) if image_size not in (None, "", 0, "0", "auto") else None
        if image_size is not None and not 32 <= image_size <= 1024:
            raise ValueError("image_size 必須在 32 … 1024 之間（建議 224 / 336 / 448）")
        neighborhood = int(src.get("neighborhood") or 1)
        if neighborhood not in NEIGHBORHOODS:
            raise ValueError(f"neighborhood 必須是 {' / '.join(str(v) for v in NEIGHBORHOODS)}")
        return cls(layers=layers, image_size=image_size, neighborhood=neighborhood)

    def to_dict(self) -> dict[str, Any]:
        return {
            "layers": list(self.layers) if isinstance(self.layers, tuple) else self.layers,
            "image_size": self.image_size,
            "neighborhood": self.neighborhood,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> FeatureSpec:
        """Artifacts written by earlier versions carry extra keys (pool / center / …); they are ignored."""
        d = dict(d or {})
        return cls.from_params({k: d[k] for k in ("layers", "image_size", "neighborhood") if k in d})

    def feature_dim(self, hidden: int, n_layers_used: int) -> int:
        return hidden * n_layers_used

    def describe(self) -> str:
        layers = ",".join(str(v) for v in self.layers) if isinstance(self.layers, tuple) else str(self.layers)
        return f"layers={layers} image_size={self.image_size or 'default'} neighborhood={self.neighborhood}"


# --- token level (torch) -------------------------------------------------------------------------------


def aggregate_neighborhood(tok, size: int):
    """PatchCore's locally aware patch features: each patch token becomes the mean of its ``size × size``
    neighbourhood on the grid (``size`` = 1 leaves the tokens untouched). ``tok`` is (B, L, D) with L a square."""
    import torch

    if size <= 1:
        return tok
    B, L, D = tok.shape
    g = round(L**0.5)
    if g * g != L:
        return tok
    grid = tok.transpose(1, 2).reshape(B, D, g, g)
    pooled = torch.nn.functional.avg_pool2d(grid, size, stride=1, padding=size // 2, count_include_pad=False)
    return pooled.reshape(B, D, L).transpose(1, 2)


def fuse_tokens(tok_list, normalize=None):
    """Per-layer patch tokens → the fused, L2-normalised patch grid (B, L, hidden × n_layers)."""
    import torch

    nf = normalize or torch.nn.functional.normalize
    return torch.cat([nf(t, dim=-1) for t in tok_list], dim=-1)


# --- vector level (numpy) ------------------------------------------------------------------------------


def l2n(x: np.ndarray) -> np.ndarray:
    x = np.asarray(x, dtype=np.float32)
    return x / (np.linalg.norm(x, axis=-1, keepdims=True) + 1e-9)


def fuse_blocks(blocks: np.ndarray) -> np.ndarray:
    """(N, n_layers, D) per-layer mean-pooled vectors → (N, n_layers × D), each block normalised first so a layer
    with a larger activation scale does not dominate, then the whole vector normalised."""
    b = l2n(np.asarray(blocks, dtype=np.float32))
    if b.ndim == 2:
        return l2n(b)
    return l2n(b.reshape(b.shape[0], -1))


def center_vector(emb: np.ndarray) -> np.ndarray:
    return np.asarray(emb, dtype=np.float32).mean(axis=0)


def apply_center(emb: np.ndarray, mu: np.ndarray | None) -> np.ndarray:
    """SimpleShot-style centring: subtract the support mean, renormalise (removes the dataset-wide direction
    every image shares, which otherwise inflates all similarities)."""
    if mu is None:
        return l2n(emb)
    return l2n(np.asarray(emb, dtype=np.float32) - np.asarray(mu, dtype=np.float32))


def patch_reference(vec: np.ndarray, hidden: int, n_layers_used: int) -> np.ndarray:
    """A fused image vector (what the bank stores) → a unit vector in the patch grid's space: per layer the block
    is renormalised so it matches the per-layer-normalised patch tokens."""
    v = np.asarray(vec, dtype=np.float32)
    if v.size != hidden * n_layers_used:
        return v / (np.linalg.norm(v) + 1e-9)
    parts = l2n(v.reshape(n_layers_used, hidden)).reshape(-1)
    return parts / (np.linalg.norm(parts) + 1e-9)


def softmax(x: np.ndarray, axis: int = 1) -> np.ndarray:
    x = np.asarray(x, dtype=np.float64)
    x = x - x.max(axis=axis, keepdims=True)
    e = np.exp(x)
    return (e / e.sum(axis=axis, keepdims=True)).astype(np.float32)


def aggregate_scores(maps: np.ndarray, agg: str) -> np.ndarray:
    """Patch anomaly maps (N, L) → image scores: ``max`` (one patch over the threshold is enough) or ``top1``
    (mean of the top 1 % patches, robust to a single noisy patch; what AnomalyDINO-style scoring uses)."""
    maps = np.asarray(maps, dtype=np.float32)
    if agg == "top1":
        k = max(1, round(0.01 * maps.shape[1]))
        return np.sort(maps, axis=1)[:, -k:].mean(axis=1)
    return maps.max(axis=1)


# --- layer diagnostics (analysis tool, layers=auto) ------------------------------------------------------


def fisher_ratio(x: np.ndarray, labels: np.ndarray) -> float:
    """Between-class scatter / within-class scatter (trace form) on L2-normalised features."""
    x = l2n(x)
    classes = np.unique(labels)
    mu = x.mean(axis=0)
    sb = 0.0
    sw = 0.0
    for c in classes:
        xc = x[labels == c]
        mc = xc.mean(axis=0)
        sb += len(xc) * float(((mc - mu) ** 2).sum())
        sw += float(((xc - mc) ** 2).sum())
    return float(sb / (sw + 1e-9))


def loo_nearest_centroid(x: np.ndarray, labels: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Leave-one-out nearest-centroid prediction per sample: (predicted label, probability of that label)."""
    x = l2n(x)
    labels = np.asarray(labels)
    classes = np.unique(labels)
    sums = np.stack([x[labels == c].sum(axis=0) for c in classes])
    counts = np.array([(labels == c).sum() for c in classes], dtype=np.float32)
    preds = np.empty(len(x), dtype=object)
    conf = np.zeros(len(x), dtype=np.float32)
    idx = {c: i for i, c in enumerate(classes)}
    for n in range(len(x)):
        s = sums.copy()
        k = counts.copy()
        i = idx[labels[n]]
        s[i] -= x[n]
        k[i] -= 1
        valid = k > 0
        protos = l2n(s[valid] / np.maximum(k[valid], 1)[:, None])
        sims = x[n : n + 1] @ protos.T
        p = softmax(sims / COSINE_TEMPERATURE)[0]
        j = int(np.argmax(sims[0]))
        preds[n] = classes[valid][j]
        conf[n] = float(p[j])
    return preds, conf


def layer_scores(blocks: np.ndarray, labels: np.ndarray, layer_ids: tuple[int, ...]) -> list[dict[str, Any]]:
    """Per layer: Fisher ratio and leave-one-out nearest-centroid accuracy of its pooled features."""
    labels = np.asarray(labels)
    out = []
    for j, layer in enumerate(layer_ids):
        x = blocks[:, j, :]
        preds, _ = loo_nearest_centroid(x, labels)
        out.append(
            {
                "layer": int(layer),
                "fisher": round(fisher_ratio(x, labels), 4),
                "loo_accuracy": round(float((preds == labels).mean()), 4),
            }
        )
    return out


def select_layers(
    blocks: np.ndarray, labels: np.ndarray, layer_ids: tuple[int, ...], max_layers: int = AUTO_MAX_LAYERS
) -> tuple[tuple[int, ...], list[dict[str, Any]]]:
    """``layers: auto``: rank every layer by LOO accuracy (Fisher ratio breaks ties) on the labelled support
    set and keep the best ``max_layers`` (always at least one)."""
    scores = layer_scores(blocks, labels, layer_ids)
    ranked = sorted(scores, key=lambda s: (-s["loo_accuracy"], -s["fisher"]))
    chosen = sorted(s["layer"] for s in ranked[: max(1, min(max_layers, len(ranked)))])
    for s in scores:
        s["selected"] = s["layer"] in chosen
    return tuple(chosen), scores


# --- heads -------------------------------------------------------------------------------------------

HEADS = ("prototype", "knn", "linear", "svm")
HEAD_ALIASES = {"logistic": "linear", "prototype+logistic": "linear"}  # artifacts from earlier versions
LINEAR_MIN_PER_CLASS = 10  # head=auto: a trained head needs this many images per class, else prototypes


def resolve_head(value: Any, min_per_class: int) -> tuple[str, str]:
    """``head`` param → (kind, reason). ``auto`` = nearest prototype with few images per class, a linear head
    once every class has LINEAR_MIN_PER_CLASS or more."""
    kind = str(value or "auto").lower()
    kind = HEAD_ALIASES.get(kind, kind)
    if kind == "auto":
        if min_per_class >= LINEAR_MIN_PER_CLASS:
            return "linear", f"every class has ≥ {LINEAR_MIN_PER_CLASS} images → linear head"
        return "prototype", f"smallest class has {min_per_class} images (< {LINEAR_MIN_PER_CLASS}) → prototypes"
    if kind not in HEADS:
        raise ValueError(f"head 必須是 auto / {' / '.join(HEADS)}，不是 {value!r}")
    return kind, "chosen by the user"


def class_prototypes(emb: np.ndarray, labels: np.ndarray) -> tuple[list[str], np.ndarray]:
    classes = sorted(set(np.asarray(labels).astype(str).tolist()))
    labels = np.asarray(labels).astype(str)
    protos = np.stack([np.asarray(emb)[labels == c].mean(axis=0) for c in classes])
    return classes, l2n(protos)


class FewShotHead:
    """Classifier on top of frozen features. ``prototype``: nearest class mean (confidence = cosine
    similarity); ``knn``: majority vote of the k nearest support images; ``linear``: a logistic-regression
    (linear-probe) head trained on the support features; ``svm``: a linear SVM. prototype / knn centre the
    features on the support mean first (SimpleShot); the trained heads do not need it. Re-fitting on cached
    features is cheap, which is what ``extend`` does."""

    def __init__(self, kind: str = "prototype", k: int | str = "auto", C: float = 1.0) -> None:
        kind = HEAD_ALIASES.get(str(kind), str(kind))
        if kind not in HEADS:
            raise ValueError(f"head 必須是 {' / '.join(HEADS)}，不是 {kind!r}")
        self.kind = kind
        self.k_param = k
        self.k = 5
        self.C = float(C)
        self.classes: list[str] = []
        self.protos: np.ndarray | None = None
        self.center: np.ndarray | None = None
        self.support: np.ndarray | None = None
        self.support_labels: np.ndarray | None = None
        self.model = None

    @property
    def centred(self) -> bool:
        return self.kind in ("prototype", "knn")

    # -- fit ------------------------------------------------------------------------------------
    def fit(self, emb: np.ndarray, labels: np.ndarray) -> FewShotHead:
        emb = l2n(emb)
        labels = np.asarray(labels).astype(str)
        counts = np.unique(labels, return_counts=True)[1]
        self.center = center_vector(emb) if self.centred else None
        x = apply_center(emb, self.center)
        self.classes, self.protos = class_prototypes(x, labels)
        self.support, self.support_labels = x, labels
        k = self.k_param
        self.k = max(1, min(int(k) if str(k) != "auto" else 5, int(counts.min()))) if self.kind == "knn" else 5
        self.model = None
        if self.kind in ("linear", "svm") and len(self.classes) >= 2:
            index = {c: i for i, c in enumerate(self.classes)}
            y = np.array([index[v] for v in labels])
            if self.kind == "svm":
                from sklearn.svm import LinearSVC

                self.model = LinearSVC(C=self.C, max_iter=5000).fit(x, y)
            else:
                from sklearn.linear_model import LogisticRegression

                self.model = LogisticRegression(C=self.C, max_iter=3000).fit(x, y)
        return self

    # -- predict --------------------------------------------------------------------------------
    def transform(self, emb: np.ndarray) -> np.ndarray:
        return apply_center(l2n(emb), self.center)

    def _model_proba(self, x: np.ndarray) -> np.ndarray:
        if hasattr(self.model, "predict_proba"):
            return np.asarray(self.model.predict_proba(x), dtype=np.float32)
        d = np.asarray(self.model.decision_function(x), dtype=np.float32)
        if d.ndim == 1:  # binary: one margin
            d = np.stack([-d, d], axis=1)
        return softmax(d)

    def predict(self, emb: np.ndarray) -> tuple[list[str], np.ndarray, np.ndarray, np.ndarray]:
        """→ (predictions, confidence, probabilities (N, K), prototype similarities (N, K))."""
        x = self.transform(emb)
        assert self.protos is not None
        sims = x @ self.protos.T
        K = len(self.classes)
        if self.kind == "knn" and self.support is not None and len(self.support) >= 1:
            ssims = x @ self.support.T
            k = min(self.k, len(self.support))
            nn = np.argsort(-ssims, axis=1)[:, :k]
            index = {c: i for i, c in enumerate(self.classes)}
            proba = np.zeros((len(x), K), dtype=np.float32)
            for n in range(len(x)):
                for j in nn[n]:
                    proba[n, index[str(self.support_labels[j])]] += 1.0 / k
            best = proba.max(axis=1, keepdims=True)
            tie = (proba == best).sum(axis=1) > 1
            if tie.any():  # ties fall back to the nearest prototype
                proba[tie] += 1e-3 * softmax(sims[tie] / COSINE_TEMPERATURE)
            conf = proba.max(axis=1)
        elif self.kind in ("linear", "svm") and self.model is not None:
            proba = self._model_proba(x)
            conf = proba.max(axis=1)
        else:  # prototype (or a trained head with a single class)
            proba = softmax(sims / COSINE_TEMPERATURE)
            conf = sims.max(axis=1)
        pred_idx = proba.argmax(axis=1)
        return [self.classes[i] for i in pred_idx], conf.astype(np.float32), proba, sims

    def class_weights(self) -> np.ndarray | None:
        """(K, D) weight rows of a linear / svm head (CAM: per-patch contribution = w · patch); None otherwise."""
        if self.model is None or not hasattr(self.model, "coef_"):
            return None
        w = np.asarray(self.model.coef_, dtype=np.float32)
        if w.shape[0] == 1 and len(self.classes) == 2:  # binary: one row for class 1, its negative for class 0
            w = np.concatenate([-w, w])
        return w

    # -- state ----------------------------------------------------------------------------------
    def meta(self) -> dict[str, Any]:
        return {"head": self.kind, "k": self.k, "C": self.C}

    @classmethod
    def from_meta(cls, meta: dict[str, Any], default_kind: str = "prototype") -> FewShotHead:
        return cls(str(meta.get("head") or default_kind), meta.get("k") or "auto", float(meta.get("C") or 1.0))
