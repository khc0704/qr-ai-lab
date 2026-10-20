"""Feature-generation options shared by the DINO families (few-shot, fine-tune, PatchCore) and the image
analysis tool: which transformer layers to read, how to pool the tokens of a layer, how to fuse layers,
centring / background removal, the distance metric, and the few-shot heads that sit on top.

Everything here is framework-light (numpy; torch only inside ``pool_layer`` / ``remove_cls_component``, which
receive tensors) so the backend tests and the analysis tool can import it without a GPU.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

# 1-based layer indices for a 12-layer ViT-S / ViT-B. Other depths are scaled proportionally (ViT-L 24 layers →
# ``mid`` = 12 / 16 / 20 / 24). DINOv2 keeps a useful amount of local detail down to layer 6; DINOv3's register
# tokens and Gram anchoring make its later blocks the stable ones, so its ``mid`` preset starts higher.
LAYER_PRESETS: dict[str, dict[str, tuple[int, ...]]] = {
    "dinov2": {"last": (12,), "last4": (9, 10, 11, 12), "mid": (6, 8, 10, 12), "spread": (3, 6, 9, 12)},
    "dinov3": {"last": (12,), "last4": (9, 10, 11, 12), "mid": (8, 10, 12), "spread": (3, 6, 9, 12)},
}
LAYER_CHOICES = ("last", "last4", "mid", "spread", "auto", "all")
POOLS = ("cls+mean", "cls", "mean", "cls+gem", "cls+attn")
FUSIONS = ("concat", "mean")
CENTERS = ("none", "support_mean")
BACKGROUNDS = ("none", "project_out_cls")
METRICS = ("cosine", "hyperbolic")
IMAGE_SIZES = (224, 336, 448)
AUTO_MAX_LAYERS = 3
GEM_P = 3.0
COSINE_TEMPERATURE = 0.1  # softmax(sims / T) turns cosine similarities into prototype probabilities


def backbone_kind(backbone_id: str, model_type: str | None = None) -> str:
    """``dinov3`` when the weights / config say so, else ``dinov2`` (DINOv1 checkpoints also load as dinov2)."""
    text = f"{backbone_id} {model_type or ''}".lower()
    return "dinov3" if "dinov3" in text else "dinov2"


def _scale(preset: tuple[int, ...], n_layers: int) -> tuple[int, ...]:
    out: list[int] = []
    for layer in preset:
        k = max(1, min(n_layers, round(layer * n_layers / 12)))
        if k not in out:
            out.append(k)
    return tuple(sorted(out))


def resolve_layers(value: Any, n_layers: int, kind: str = "dinov2") -> tuple[int, ...]:
    """``layers`` param → 1-based layer indices to read. A preset name is scaled to this backbone's depth,
    ``all`` is every layer (also what ``auto`` reads before it picks), a list / comma string is used as-is
    (negative = from the end)."""
    if n_layers < 1:
        raise ValueError("backbone has no layers")
    if value is None or value == "" or value == "last":
        return (n_layers,)
    if isinstance(value, str) and value.strip().lower() in ("all", "auto"):
        return tuple(range(1, n_layers + 1))
    if isinstance(value, str) and value.strip().lower() in LAYER_PRESETS["dinov2"]:
        presets = LAYER_PRESETS.get(kind) or LAYER_PRESETS["dinov2"]
        return _scale(presets[value.strip().lower()], n_layers)
    items = value.split(",") if isinstance(value, str) else list(value) if isinstance(value, (list, tuple)) else [value]
    out: list[int] = []
    for item in items:
        s = str(item).strip()
        if not s:
            continue
        try:
            k = int(s)
        except ValueError as e:
            raise ValueError(f"layers 不認得 {s!r}：可用 {', '.join(LAYER_CHOICES)} 或層數列表（例：6,9,12）") from e
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

    layers: Any = "last"  # preset name, "auto", or a tuple of 1-based layer indices
    layer_fusion: str = "concat"
    pool: str = "cls+mean"
    center: str = "none"
    background: str = "none"
    metric: str = "cosine"
    image_size: int | None = None

    @classmethod
    def from_params(cls, p: dict[str, Any], **overrides: Any) -> FeatureSpec:
        src = {**p, **overrides}
        layers = src.get("layers", "last")
        if isinstance(layers, (list, tuple)):
            layers = tuple(int(v) for v in layers)
        elif layers is not None and not isinstance(layers, str):
            layers = (int(layers),)
        elif isinstance(layers, str):
            layers = layers.strip().lower() or "last"
            if layers not in LAYER_CHOICES and not any(ch.isdigit() for ch in layers):
                raise ValueError(f"layers 不認得 {layers!r}，可用：{', '.join(LAYER_CHOICES)} 或層數列表")
        spec = cls(
            layers=layers,
            layer_fusion=str(src.get("layer_fusion") or "concat").lower(),
            pool=str(src.get("pool") or "cls+mean").lower(),
            center=str(src.get("center") or "none").lower(),
            background=str(src.get("background") or "none").lower(),
            metric=str(src.get("metric") or "cosine").lower(),
            image_size=int(src["image_size"]) if src.get("image_size") not in (None, "", 0, "0") else None,
        )
        for name, value, allowed in (
            ("layer_fusion", spec.layer_fusion, FUSIONS),
            ("pool", spec.pool, POOLS),
            ("center", spec.center, CENTERS),
            ("background", spec.background, BACKGROUNDS),
            ("metric", spec.metric, METRICS),
        ):
            if value not in allowed:
                raise ValueError(f"{name} 必須是 {' / '.join(allowed)}，不是 {value!r}")
        if spec.image_size is not None and not 32 <= spec.image_size <= 1024:
            raise ValueError("image_size 必須在 32 … 1024 之間（建議 224 / 336 / 448）")
        return spec

    def to_dict(self) -> dict[str, Any]:
        return {
            "layers": list(self.layers) if isinstance(self.layers, tuple) else self.layers,
            "layer_fusion": self.layer_fusion,
            "pool": self.pool,
            "center": self.center,
            "background": self.background,
            "metric": self.metric,
            "image_size": self.image_size,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> FeatureSpec:
        return cls.from_params(dict(d or {}))

    @property
    def has_patch_part(self) -> bool:
        return self.pool != "cls"

    @property
    def wants_attention(self) -> bool:
        return self.pool == "cls+attn"

    def block_dim(self, hidden: int) -> int:
        """Size of one layer's pooled vector."""
        return hidden * (2 if self.pool in ("cls+mean", "cls+gem", "cls+attn") else 1)

    def feature_dim(self, hidden: int, n_layers_used: int) -> int:
        return self.block_dim(hidden) * (n_layers_used if self.layer_fusion == "concat" else 1)

    def describe(self) -> str:
        layers = ",".join(str(v) for v in self.layers) if isinstance(self.layers, tuple) else str(self.layers)
        return (
            f"layers={layers} fusion={self.layer_fusion} pool={self.pool} center={self.center} "
            f"background={self.background} metric={self.metric} image_size={self.image_size or 'default'}"
        )


# --- token level (torch) -------------------------------------------------------------------------------


def remove_cls_component(tok, cls):
    """Background removal: drop the component of every patch token that lies along its image's CLS direction
    (``tok − (tok·ĉ) ĉ``); what remains is what makes the patch differ from the image-level summary."""
    import torch

    c = torch.nn.functional.normalize(cls, dim=-1)[:, None, :]  # (B, 1, D)
    return tok - (tok * c).sum(dim=-1, keepdim=True) * c


def pool_layer(cls, tok, pool: str, attn=None):
    """One layer's tokens → one vector per image. ``cls`` (B, D), ``tok`` (B, L, D), ``attn`` (B, L) CLS→patch
    attention weights (only for ``cls+attn``)."""
    import torch

    if pool == "cls":
        return cls
    if pool == "mean":
        return tok.mean(dim=1)
    if pool == "cls+gem":
        gem = tok.clamp(min=1e-6).pow(GEM_P).mean(dim=1).pow(1.0 / GEM_P)
        return torch.cat([cls, gem], dim=1)
    if pool == "cls+attn" and attn is not None:
        w = attn / (attn.sum(dim=1, keepdim=True) + 1e-9)
        return torch.cat([cls, (w[:, :, None] * tok).sum(dim=1)], dim=1)
    return torch.cat([cls, tok.mean(dim=1)], dim=1)


# --- vector level (numpy) ------------------------------------------------------------------------------


def l2n(x: np.ndarray) -> np.ndarray:
    x = np.asarray(x, dtype=np.float32)
    return x / (np.linalg.norm(x, axis=-1, keepdims=True) + 1e-9)


def fuse_blocks(blocks: np.ndarray, fusion: str = "concat") -> np.ndarray:
    """(N, n_layers, F) per-layer pooled vectors → (N, F') fused, L2-normalised. Each block is normalised first
    so a layer with a larger activation scale does not dominate."""
    b = l2n(np.asarray(blocks, dtype=np.float32))
    if b.ndim == 2:
        return l2n(b)
    if fusion == "mean":
        return l2n(b.mean(axis=1))
    return l2n(b.reshape(b.shape[0], -1))


def center_vector(emb: np.ndarray) -> np.ndarray:
    return np.asarray(emb, dtype=np.float32).mean(axis=0)


def apply_center(emb: np.ndarray, mu: np.ndarray | None) -> np.ndarray:
    """SimpleShot-style centring: subtract the support mean, renormalise (removes the dataset-wide direction
    every image shares, which otherwise inflates all similarities)."""
    if mu is None:
        return l2n(emb)
    return l2n(np.asarray(emb, dtype=np.float32) - np.asarray(mu, dtype=np.float32))


def to_ball(x: np.ndarray, c: float = 1.0) -> np.ndarray:
    """Exponential map at the origin of the Poincaré ball: ``tanh(√c‖x‖) x / (√c‖x‖)``."""
    x = np.asarray(x, dtype=np.float64)
    n = np.linalg.norm(x, axis=-1, keepdims=True) + 1e-9
    return np.tanh(np.sqrt(c) * n) * x / (np.sqrt(c) * n)


def poincare_dist(u: np.ndarray, v: np.ndarray, c: float = 1.0, chunk: int = 256) -> np.ndarray:
    """Pairwise hyperbolic distance between rows of ``u`` (N, D) and ``v`` (K, D), both already in the ball."""
    u = np.asarray(u, dtype=np.float64)
    v = np.asarray(v, dtype=np.float64)
    sc = np.sqrt(c)
    vv = (v * v).sum(axis=1)  # (K,)
    out = np.zeros((len(u), len(v)), dtype=np.float32)
    for s in range(0, len(u), chunk):
        a = u[s : s + chunk]
        uu = (a * a).sum(axis=1)[:, None]  # (n, 1)
        uv = a @ v.T  # (n, K)
        # Möbius addition (−a) ⊕ v, then ‖·‖
        num_a = (1 - 2 * c * uv + c * vv[None, :])[:, :, None] * (-a)[:, None, :]
        num_v = (1 - c * uu)[:, :, None] * v[None, :, :]
        den = 1 - 2 * c * uv + c * c * uu * vv[None, :]
        m = (num_a + num_v) / den[:, :, None]
        norm = np.clip(sc * np.linalg.norm(m, axis=-1), 0, 1 - 1e-7)
        out[s : s + chunk] = (2 / sc) * np.arctanh(norm)
    return out


def similarities(emb: np.ndarray, ref: np.ndarray, metric: str = "cosine") -> np.ndarray:
    """(N, K) "higher = closer" scores: cosine similarity, or minus the Poincaré distance."""
    if metric == "hyperbolic":
        return -poincare_dist(to_ball(emb), to_ball(ref))
    return np.asarray(emb, dtype=np.float32) @ np.asarray(ref, dtype=np.float32).T


def softmax(x: np.ndarray, axis: int = 1) -> np.ndarray:
    x = np.asarray(x, dtype=np.float64)
    x = x - x.max(axis=axis, keepdims=True)
    e = np.exp(x)
    return (e / e.sum(axis=axis, keepdims=True)).astype(np.float32)


# --- layer diagnostics -------------------------------------------------------------------------------


def fisher_ratio(x: np.ndarray, labels: np.ndarray) -> float:
    """Between-class scatter / within-class scatter (trace form) on L2-normalised features; larger = the
    classes sit further apart than their own spread."""
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


def loo_nearest_centroid(x: np.ndarray, labels: np.ndarray, metric: str = "cosine") -> tuple[np.ndarray, np.ndarray]:
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
        sims = similarities(x[n : n + 1], protos, metric)[0]
        p = softmax(sims[None, :] / (COSINE_TEMPERATURE if metric == "cosine" else 1.0))[0]
        j = int(np.argmax(sims))
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

HEADS = ("prototype", "knn", "logistic", "svm", "prototype+logistic")


def class_prototypes(emb: np.ndarray, labels: np.ndarray) -> tuple[list[str], np.ndarray]:
    classes = sorted(set(np.asarray(labels).astype(str).tolist()))
    labels = np.asarray(labels).astype(str)
    protos = np.stack([np.asarray(emb)[labels == c].mean(axis=0) for c in classes])
    return classes, l2n(protos)


class FewShotHead:
    """Classifier on top of frozen features. ``prototype``: nearest class mean (confidence = similarity);
    ``knn``: majority vote of the k nearest support images; ``logistic`` / ``svm``: a trained head on the
    support features; ``prototype+logistic``: average of the prototype probabilities and the logistic head
    (robust with 1–3 images per class, sharper once there are more). Re-fitting on cached features is cheap,
    which is what ``extend`` does."""

    def __init__(self, kind: str = "prototype", k: int = 5, metric: str = "cosine", C: float = 1.0) -> None:
        if kind not in HEADS:
            raise ValueError(f"head 必須是 {' / '.join(HEADS)}，不是 {kind!r}")
        self.kind = kind
        self.k = max(1, int(k))
        self.metric = metric
        self.C = float(C)
        self.classes: list[str] = []
        self.protos: np.ndarray | None = None
        self.support: np.ndarray | None = None
        self.support_labels: np.ndarray | None = None
        self.model = None

    # -- fit ------------------------------------------------------------------------------------
    def fit(self, emb: np.ndarray, labels: np.ndarray) -> FewShotHead:
        emb = l2n(emb)
        labels = np.asarray(labels).astype(str)
        self.classes, self.protos = class_prototypes(emb, labels)
        self.support, self.support_labels = emb, labels
        self.model = None
        trainable = self.kind in ("logistic", "svm", "prototype+logistic")
        if trainable and len(self.classes) >= 2:
            index = {c: i for i, c in enumerate(self.classes)}
            y = np.array([index[v] for v in labels])
            if self.kind == "svm":
                from sklearn.svm import SVC

                self.model = SVC(kernel="linear", C=self.C).fit(emb, y)
            else:
                from sklearn.linear_model import LogisticRegression

                self.model = LogisticRegression(C=self.C, max_iter=3000).fit(emb, y)
        return self

    # -- predict --------------------------------------------------------------------------------
    def proto_scores(self, emb: np.ndarray) -> np.ndarray:
        assert self.protos is not None
        return similarities(l2n(emb), self.protos, self.metric)

    def _proto_proba(self, sims: np.ndarray) -> np.ndarray:
        return softmax(sims / (COSINE_TEMPERATURE if self.metric == "cosine" else 1.0))

    def _model_proba(self, emb: np.ndarray) -> np.ndarray:
        if hasattr(self.model, "predict_proba"):
            return np.asarray(self.model.predict_proba(emb), dtype=np.float32)
        d = np.asarray(self.model.decision_function(emb), dtype=np.float32)
        if d.ndim == 1:  # binary SVM: one margin
            d = np.stack([-d, d], axis=1)
        return softmax(d)

    def predict(self, emb: np.ndarray) -> tuple[list[str], np.ndarray, np.ndarray, np.ndarray]:
        """→ (predictions, confidence, probabilities (N, K), prototype similarities (N, K))."""
        emb = l2n(emb)
        sims = self.proto_scores(emb)
        K = len(self.classes)
        if self.kind == "knn" and self.support is not None and len(self.support) >= 1:
            ssims = similarities(emb, self.support, self.metric)
            k = min(self.k, len(self.support))
            nn = np.argsort(-ssims, axis=1)[:, :k]
            index = {c: i for i, c in enumerate(self.classes)}
            proba = np.zeros((len(emb), K), dtype=np.float32)
            for n in range(len(emb)):
                for j in nn[n]:
                    proba[n, index[str(self.support_labels[j])]] += 1.0 / k
            # ties fall back to the nearest prototype
            best = proba.max(axis=1, keepdims=True)
            tie = (proba == best).sum(axis=1) > 1
            if tie.any():
                proba[tie] += 1e-3 * self._proto_proba(sims[tie])
            conf = proba.max(axis=1)
        elif self.kind in ("logistic", "svm") and self.model is not None:
            proba = self._model_proba(emb)
            conf = proba.max(axis=1)
        elif self.kind == "prototype+logistic" and self.model is not None:
            proba = 0.5 * (self._proto_proba(sims) + self._model_proba(emb))
            conf = proba.max(axis=1)
        else:  # prototype (or a trainable head with a single class)
            proba = self._proto_proba(sims)
            # cosine: the similarity itself is the natural confidence; hyperbolic: a distance → use the probability
            conf = sims.max(axis=1) if self.metric == "cosine" else proba.max(axis=1)
        pred_idx = proba.argmax(axis=1)
        preds = [self.classes[i] for i in pred_idx]
        return preds, conf.astype(np.float32), proba, sims

    # -- state ----------------------------------------------------------------------------------
    def meta(self) -> dict[str, Any]:
        return {"head": self.kind, "k": self.k, "metric": self.metric, "C": self.C}

    @classmethod
    def from_meta(cls, meta: dict[str, Any], default_kind: str = "prototype") -> FewShotHead:
        return cls(
            str(meta.get("head") or default_kind),
            int(meta.get("k") or 5),
            str(meta.get("metric") or "cosine"),
            float(meta.get("C") or 1.0),
        )
