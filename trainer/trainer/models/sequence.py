"""Sequence / spectrum families (PyTorch): patch autoencoder and spectrum masked autoencoder.

Both learn an embedding per window plus a reconstruction error. Inference modes:
  score    → anomaly score + threshold verdict
  embed    → embedding vector per sample (also saved as output/embeddings.npy)
  retrieve → most / least similar samples in the reference set (the training windows, or the input itself)
  predict  → spectrum MAE with task=regression: value from a ridge head on the embedding (e.g. CD / thickness)

Feature options (spectrum MAE): ``embed_layers`` (last / mid / all encoder blocks) and ``embed_pool`` (mean /
max / gem / meanmax over the patch tokens) decide the embedding; ``score_method`` = ``recon`` (masked
reconstruction error) or ``patch_bank`` (kNN distance of every patch token to a bank of normal patch tokens,
PatchCore-style) decides the anomaly score. Both families report per-patch scores, so ``score`` also says
which band (sample range) of the curve deviates.
"""

from __future__ import annotations

import itertools
import math
from pathlib import Path
from typing import Any

import joblib
import numpy as np

from trainer import jsonsafe
from trainer import metrics as M
from trainer.data.split import holdout
from trainer.dataset import Dataset
from trainer.log import info
from trainer.models.base import ArtifactOut, BaseInferencer, BaseTrainer, PredictResult
from trainer.models.tabular import _binary_anomaly_labels


def _torch():
    import torch

    return torch


def as_windows(X: Any, T: int | None = None) -> np.ndarray:
    """(N, T, C) float32; a different window length is resampled onto T (linear interpolation)."""
    X = np.asarray(X, dtype=np.float32)
    if X.ndim == 2:
        X = X[:, :, None]
    if T is not None and X.shape[1] != T:
        src = np.linspace(0, 1, X.shape[1])
        dst = np.linspace(0, 1, T)
        X = np.stack(
            [np.stack([np.interp(dst, src, X[n, :, c]) for c in range(X.shape[2])], axis=1) for n in range(len(X))]
        )
        X = X.astype(np.float32)
    return X


def patchify(x, patch: int):
    """torch (B, T, C) → (B, L, patch*C); T is padded by edge replication to a multiple of patch."""
    torch = _torch()
    B, T, C = x.shape
    pad = (-T) % patch
    if pad:
        x = torch.cat([x, x[:, -1:, :].expand(B, pad, C)], dim=1)
    L = x.shape[1] // patch
    return x.reshape(B, L, patch * C)


class PatchAE:
    """Patch autoencoder: each patch is embedded, a learned position is added, and the whole window is
    compressed to one latent vector (so a peak that moves to another position is an anomaly)."""

    @staticmethod
    def build(in_dim: int, n_patches: int, latent: int, layers: int, hidden: int = 64):
        torch = _torch()
        nn = torch.nn

        def mlp(dims: list[int]) -> nn.Sequential:
            mods: list[nn.Module] = []
            for i, (a, b) in enumerate(itertools.pairwise(dims)):
                mods.append(nn.Linear(a, b))
                if i < len(dims) - 2:
                    mods.append(nn.GELU())
            return nn.Sequential(*mods)

        class Net(nn.Module):
            def __init__(self) -> None:
                super().__init__()
                self.embed_in = nn.Sequential(nn.Linear(in_dim, hidden), nn.GELU())
                self.pos = nn.Parameter(torch.zeros(1, n_patches, hidden))
                nn.init.trunc_normal_(self.pos, std=0.02)
                inner = [hidden] * max(0, layers - 1)
                self.enc = mlp([n_patches * hidden, *inner, latent])
                self.dec = mlp([latent, *inner, n_patches * hidden])
                self.out = nn.Linear(hidden, in_dim)

            def tokens(self, patches):
                """(B, L, hidden) per-patch tokens before the bottleneck (what a patch bank stores)."""
                return self.embed_in(patches) + self.pos

            def embed(self, patches):
                return self.enc(self.tokens(patches).flatten(1))

            def forward(self, patches):
                z = self.embed(patches)
                h = torch.nn.functional.gelu(self.dec(z)).view(patches.shape[0], n_patches, hidden)
                return self.out(h), z

            def patch_errors(self, patches):
                recon, _ = self(patches)
                return ((recon - patches) ** 2).mean(dim=-1)  # (B, L)

            def loss_and_score(self, patches):
                err = self.patch_errors(patches)
                return err.mean(), err.mean(dim=1)

        return Net()


EMBED_LAYERS = ("last", "mid", "all")
EMBED_POOLS = ("mean", "max", "gem", "meanmax")
SCORE_METHODS = ("recon", "patch_bank")


def embed_layer_ids(choice: str, depth: int) -> list[int]:
    """0-based encoder blocks whose outputs form the embedding: ``last`` = the final block, ``mid`` = the later
    half (block depth/2 … depth), ``all`` = every block."""
    if choice == "all":
        return list(range(depth))
    if choice == "mid":
        return list(range(max(0, depth // 2 - 1), depth)) if depth > 1 else [0]
    return [depth - 1]


def pool_tokens(tok, pool: str):
    """(B, L, D) → (B, D) or (B, 2D) for meanmax."""
    torch = _torch()
    if pool == "max":
        return tok.max(dim=1).values
    if pool == "gem":
        return tok.clamp(min=1e-6).pow(3.0).mean(dim=1).pow(1.0 / 3.0)
    if pool == "meanmax":
        return torch.cat([tok.mean(dim=1), tok.max(dim=1).values], dim=1)
    return tok.mean(dim=1)


class SpectrumMAE:
    @staticmethod
    def build(
        in_dim: int,
        n_patches: int,
        dim: int,
        depth: int,
        heads: int,
        mask_ratio: float,
        embed_layers: str = "last",
        embed_pool: str = "mean",
    ):
        torch = _torch()
        nn = torch.nn
        layer_ids = embed_layer_ids(embed_layers, depth)

        class Net(nn.Module):
            def __init__(self) -> None:
                super().__init__()
                self.mask_ratio = mask_ratio
                self.embed_layers = layer_ids
                self.embed_pool = embed_pool
                self.embed_in = nn.Linear(in_dim, dim)
                self.pos = nn.Parameter(torch.zeros(1, n_patches, dim))
                nn.init.trunc_normal_(self.pos, std=0.02)
                layer = nn.TransformerEncoderLayer(
                    dim, heads, dim * 4, dropout=0.0, activation="gelu", batch_first=True
                )
                self.encoder = nn.TransformerEncoder(layer, depth)
                self.mask_token = nn.Parameter(torch.zeros(1, 1, dim))
                dlayer = nn.TransformerEncoderLayer(
                    dim, heads, dim * 4, dropout=0.0, activation="gelu", batch_first=True
                )
                self.decoder = nn.TransformerEncoder(dlayer, 1)
                self.head = nn.Linear(dim, in_dim)

            def _blocks(self, tok):
                """Output of every encoder block (the encoder is run block by block)."""
                outs = []
                for layer in self.encoder.layers:
                    tok = layer(tok)
                    outs.append(tok)
                if self.encoder.norm is not None:
                    outs[-1] = self.encoder.norm(outs[-1])
                return outs

            def tokens(self, patches):
                """(B, L, dim) final-block tokens of the unmasked window (what a patch bank stores)."""
                return self._blocks(self.embed_in(patches) + self.pos)[-1]

            def embed(self, patches):
                outs = self._blocks(self.embed_in(patches) + self.pos)
                parts = [pool_tokens(outs[i], self.embed_pool) for i in self.embed_layers]
                return torch.cat(parts, dim=1) if len(parts) > 1 else parts[0]

            def patch_errors(self, patches, reps: int = 3):
                """(B, L) reconstruction error per patch, averaged over ``reps`` random masks (a patch that was
                never masked takes the mean of the others)."""
                total = torch.zeros(patches.shape[0], patches.shape[1], device=patches.device)
                count = torch.zeros_like(total)
                for r in range(reps):
                    gen = torch.Generator(device=patches.device).manual_seed(r)
                    err, mask = self._masked_errors(patches, gen)
                    total += err * mask
                    count += mask
                out = total / count.clamp(min=1)
                never = count == 0
                if never.any():
                    fill = (total.sum(dim=1) / count.sum(dim=1).clamp(min=1))[:, None].expand_as(out)
                    out = torch.where(never, fill, out)
                return out

            def forward(self, patches, generator=None):
                err, mask = self._masked_errors(patches, generator)
                per_sample = (err * mask).sum(dim=1) / mask.sum(dim=1)
                return per_sample.mean(), per_sample

            def _masked_errors(self, patches, generator=None):
                B, L, _ = patches.shape
                n_mask = max(1, round(L * self.mask_ratio))
                noise = torch.rand(B, L, device=patches.device, generator=generator)
                ids_shuffle = noise.argsort(dim=1)
                ids_restore = ids_shuffle.argsort(dim=1)
                ids_keep = ids_shuffle[:, : L - n_mask]
                tok = self.embed_in(patches) + self.pos
                vis = torch.gather(tok, 1, ids_keep[:, :, None].expand(-1, -1, tok.shape[2]))
                enc = self.encoder(vis)
                mask_tokens = self.mask_token.expand(B, n_mask, -1)
                full = torch.cat([enc, mask_tokens], dim=1)
                full = torch.gather(full, 1, ids_restore[:, :, None].expand(-1, -1, full.shape[2])) + self.pos
                pred = self.head(self.decoder(full))
                mask = torch.zeros(B, L, device=patches.device)
                mask[:, L - n_mask :] = 1
                mask = torch.gather(mask, 1, ids_restore)
                err = ((pred - patches) ** 2).mean(dim=-1)
                return err, mask

            def loss_and_score(self, patches, generator=None):
                return self(patches, generator)

        return Net()


def build_net(c: dict[str, Any]):
    if c["kind"] == "mae":
        return SpectrumMAE.build(
            c["in_dim"],
            c["n_patches"],
            c["dim"],
            c["depth"],
            c["heads"],
            c["mask_ratio"],
            str(c.get("embed_layers") or "last"),
            str(c.get("embed_pool") or "mean"),
        )
    return PatchAE.build(c["in_dim"], c["n_patches"], c["latent"], c["layers"])


def _patch_bank_scores(model, x, bank, k: int, device, batch: int = 256) -> np.ndarray:
    """(N, L) distance of every patch token to its k nearest bank tokens (PatchCore in 1-D)."""
    torch = _torch()
    bank_t = torch.as_tensor(np.asarray(bank, dtype=np.float32)).to(device)
    out = []
    with torch.no_grad():
        for s in range(0, len(x), batch):
            tok = model.tokens(x[s : s + batch].to(device))  # (B, L, D)
            B, L, D = tok.shape
            d = torch.cdist(tok.reshape(-1, D), bank_t)
            out.append(d.topk(min(k, bank_t.shape[0]), largest=False).values.mean(dim=1).reshape(B, L).cpu().numpy())
    return np.concatenate(out) if out else np.zeros((0, 1), np.float32)


def _patch_coreset(model, x, ratio: float, device, cap: int = 20000, seed: int = 42) -> np.ndarray:
    torch = _torch()
    toks = []
    with torch.no_grad():
        for s in range(0, len(x), 256):
            tok = model.tokens(x[s : s + 256].to(device))
            toks.append(tok.reshape(-1, tok.shape[-1]).cpu().numpy())
    flat = np.concatenate(toks)
    rng = np.random.default_rng(seed)
    size = min(len(flat), max(1000, int(len(flat) * ratio)) if len(flat) > 1000 else len(flat), cap)
    return flat[rng.choice(len(flat), size=size, replace=False)].astype(np.float32)


class _SeqTrainer(BaseTrainer):
    framework = "torch"
    kind = "ae"  # ae | mae

    def __init__(self, family: str, task: str | None, params: dict[str, Any], ctx) -> None:
        super().__init__(family, task, params, ctx)
        self.inference_modes = ["score", "embed", "retrieve"] + (["predict"] if task == "regression" else [])
        self.model = None
        self.head = None
        self.threshold: float | None = None
        self.reference: dict[str, Any] = {}
        self.config: dict[str, Any] = {}
        self.norm: tuple[np.ndarray, np.ndarray] = (np.zeros(1), np.ones(1))
        self.patch_bank: np.ndarray | None = None

    # -- model ---------------------------------------------------------------------------------
    def _build(self, T: int, C: int):
        p = self.params
        patch = int(p.get("patch_size", 16))
        L = math.ceil(T / patch)
        in_dim = patch * C
        score_method = str(p.get("score_method") or "recon").lower()
        if score_method not in SCORE_METHODS:
            raise ValueError(f"score_method 必須是 {' / '.join(SCORE_METHODS)}，不是 {score_method!r}")
        if self.kind == "mae":
            dim = int(p.get("dim", 64))
            heads = int(p.get("heads", 4))
            heads = max(1, min(heads, dim // 8)) if dim % heads else heads
            embed_layers = str(p.get("embed_layers") or "last").lower()
            embed_pool = str(p.get("embed_pool") or "mean").lower()
            if embed_layers not in EMBED_LAYERS:
                raise ValueError(f"embed_layers 必須是 {' / '.join(EMBED_LAYERS)}，不是 {embed_layers!r}")
            if embed_pool not in EMBED_POOLS:
                raise ValueError(f"embed_pool 必須是 {' / '.join(EMBED_POOLS)}，不是 {embed_pool!r}")
            self.config = {
                "kind": "mae",
                "patch": patch,
                "in_dim": in_dim,
                "n_patches": L,
                "dim": dim,
                "depth": int(p.get("depth", 4)),
                "heads": heads,
                "mask_ratio": float(p.get("mask_ratio", 0.5)),
                "embed_layers": embed_layers,
                "embed_pool": embed_pool,
                "score_method": score_method,
                "T": T,
                "C": C,
            }
            return build_net(self.config)
        self.config = {
            "kind": "ae",
            "patch": patch,
            "in_dim": in_dim,
            "n_patches": L,
            "latent": int(p.get("latent", 32)),
            "layers": int(p.get("layers", 3)),
            "score_method": score_method,
            "T": T,
            "C": C,
        }
        return build_net(self.config)

    def _tensor(self, X: np.ndarray):
        torch = _torch()
        mean, std = self.norm
        x = torch.from_numpy((X - mean) / std).float()
        return patchify(x, self.config["patch"])

    # -- fit -----------------------------------------------------------------------------------
    def fit(self, ds: Dataset) -> None:
        torch = _torch()
        torch.manual_seed(int(self.params.get("seed", 42)))
        X = as_windows(ds.X)
        N, T, C = X.shape
        y = ds.y
        if self.task == "regression":
            if y is None:
                raise ValueError("迴歸需要標籤（spec.label）")
            y = np.asarray(y, dtype=float)
            tr, va = holdout(N, None, None)
            train_idx, val_idx = tr, va
        elif y is not None and len(y) == N:
            yb = _binary_anomaly_labels(y)
            normal = np.flatnonzero(yb == 0)
            tr, va_n = holdout(len(normal), None, None)
            train_idx = normal[tr]
            val_idx = np.concatenate([normal[va_n], np.flatnonzero(yb == 1)])
            y = yb
        else:
            train_idx, val_idx = holdout(N, None, None)
        self.norm = (X[train_idx].mean(axis=(0, 1)), X[train_idx].std(axis=(0, 1)) + 1e-6)
        device = self.ctx.device
        self.model = self._build(T, C).to(device)
        xtr = self._tensor(X[train_idx])
        xva = self._tensor(X[val_idx])
        epochs = int(self.params.get("epochs", 50))
        batch = int(self.params.get("batch", 128))
        opt = torch.optim.AdamW(self.model.parameters(), lr=float(self.params.get("lr", 1e-3)), weight_decay=1e-4)
        sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=max(1, epochs))
        info(
            f"{self.family}: train={len(train_idx)} val={len(val_idx)} T={T} C={C} config={self.config} device={device}"
        )
        for epoch in range(1, epochs + 1):
            self.model.train()
            perm = torch.randperm(len(xtr))
            total = 0.0
            for s in range(0, len(xtr), batch):
                xb = xtr[perm[s : s + batch]].to(device)
                loss, _ = self.model.loss_and_score(xb)
                opt.zero_grad(set_to_none=True)
                loss.backward()
                torch.nn.utils.clip_grad_norm_(self.model.parameters(), 1.0)
                opt.step()
                total += loss.detach().item() * len(xb)
            sched.step()
            train_loss = total / max(1, len(xtr))
            val_scores = self._scores(xva)
            ep: dict[str, float] = {"loss": train_loss, "val_loss": float(val_scores.mean())}
            if self.task != "regression" and y is not None and len(np.unique(y[val_idx])) == 2:
                ep["auroc"] = M.anomaly(val_scores, y[val_idx])["auroc"]
            info(f"epoch {epoch}/{epochs} " + " ".join(f"{k}={v:.5f}" for k, v in ep.items()))
            self.ctx.epoch(epoch, ep)
            self.ctx.progress(epoch / epochs, "training")
        # reference embeddings + threshold from the training windows
        if self.config["score_method"] == "patch_bank":
            self.patch_bank = _patch_coreset(self.model, xtr, float(self.params.get("coreset_ratio", 0.1)), device)
            info(f"{self.family}: patch bank {len(self.patch_bank):,} tokens (k={int(self.params.get('bank_k', 3))})")
        train_scores = self._scores(xtr)
        self.threshold = float(np.percentile(train_scores, 99))
        emb = self._embed(xtr)
        self.reference = {
            "embeddings": emb,
            "ids": np.array([ds.ids[i] for i in train_idx]),
            "scores": train_scores,
        }
        val_scores = self._scores(xva)
        if self.task == "regression":
            from sklearn.linear_model import Ridge

            self.head = Ridge(alpha=float(self.params.get("ridge_alpha", 1.0))).fit(emb, y[train_idx])
            pred = self.head.predict(self._embed(xva))
            self.metrics = M.regression(y[val_idx], pred)
            self.metrics["val_loss"] = float(val_scores.mean())
        else:
            labels = y[val_idx] if (y is not None and len(np.unique(y[val_idx])) == 2) else None
            self.metrics = M.anomaly(val_scores, labels, self.threshold)
        self.meta.update({"threshold": self.threshold, "config": self.config})
        info(f"{self.family}: " + ", ".join(f"{k}={v:.4f}" for k, v in self.metrics.items()))

    @staticmethod
    def _batches(x, size: int = 256):
        for s in range(0, len(x), size):
            yield x[s : s + size]

    def _scores(self, x) -> np.ndarray:
        return _window_scores(
            self.model, x, self.config, self.patch_bank, int(self.params.get("bank_k", 3)), self.ctx.device
        )[0]

    def _embed(self, x) -> np.ndarray:
        torch = _torch()
        self.model.eval()
        out = []
        with torch.no_grad():
            for xb in self._batches(x):
                out.append(self.model.embed(xb.to(self.ctx.device)).cpu().numpy())
        return np.concatenate(out) if out else np.zeros((0, 1), np.float32)

    # -- export --------------------------------------------------------------------------------
    def export(self, out: Path) -> list[ArtifactOut]:
        torch = _torch()
        model_dir = out / "model"
        model_dir.mkdir(parents=True, exist_ok=True)
        torch.save(
            {
                "state_dict": self.model.state_dict(),
                "config": self.config,
                "norm_mean": self.norm[0].tolist(),
                "norm_std": self.norm[1].tolist(),
                "threshold": self.threshold,
                **({"patch_bank": torch.as_tensor(self.patch_bank)} if self.patch_bank is not None else {}),
            },
            model_dir / "model.pt",
        )
        np.savez_compressed(
            model_dir / "reference.npz",
            embeddings=self.reference["embeddings"].astype(np.float32),
            ids=self.reference["ids"].astype(str),
            scores=self.reference["scores"].astype(np.float32),
        )
        if self.head is not None:
            joblib.dump(self.head, model_dir / "head.joblib")
        meta = {
            "threshold": self.threshold,
            "config": self.config,
            "metrics": self.metrics,
            "bank_k": int(self.params.get("bank_k", 3)),
        }
        (model_dir / "metadata.json").write_text(jsonsafe.dumps(meta, indent=2), encoding="utf-8")
        return [
            ArtifactOut(
                name=self.family.split(".")[-1],
                kind="model",
                path="model",
                framework=self.framework,
                metrics=self.metrics,
                metadata=meta,
            )
        ]


def _window_scores(model, x, config: dict[str, Any], bank, k: int, device) -> tuple[np.ndarray, np.ndarray]:
    """→ (window score (N,), per-patch scores (N, L)). ``recon``: reconstruction error per patch (MAE: averaged
    over 3 random masks), window score = mean; ``patch_bank``: kNN distance per patch, window score = max."""
    torch = _torch()
    model.eval()
    if config.get("score_method") == "patch_bank" and bank is not None:
        maps = _patch_bank_scores(model, x, bank, k, device)
        return maps.max(axis=1).astype(np.float32), maps
    out = []
    with torch.no_grad():
        for s in range(0, len(x), 256):
            xb = x[s : s + 256].to(device)
            out.append(model.patch_errors(xb).cpu().numpy())
    maps = np.concatenate(out) if out else np.zeros((0, 1), np.float32)
    return maps.mean(axis=1).astype(np.float32), maps


class PatchAutoencoderTrainer(_SeqTrainer):
    kind = "ae"


class SpectrumMAETrainer(_SeqTrainer):
    kind = "mae"


class _SeqInferencer(BaseInferencer):
    def load(self, model_path: Path, metadata: dict[str, Any]) -> None:
        torch = _torch()
        blob = torch.load(model_path / "model.pt", map_location="cpu", weights_only=True)
        self.config = blob["config"]
        self.config.setdefault("score_method", "recon")
        self.model = build_net(self.config)
        self.model.load_state_dict(blob["state_dict"])
        self.patch_bank = blob["patch_bank"].numpy() if "patch_bank" in blob else None
        self.bank_k = int((metadata or {}).get("bank_k") or 3)
        self.model.to(self.ctx.device).eval()
        self.norm = (
            np.asarray(blob["norm_mean"], np.float32),
            np.asarray(blob["norm_std"], np.float32),
        )
        self.threshold = blob.get("threshold")
        ref = np.load(model_path / "reference.npz", allow_pickle=False)
        self.reference = {
            "embeddings": ref["embeddings"],
            "ids": ref["ids"].astype(str),
            "scores": ref["scores"],
        }
        head = model_path / "head.joblib"
        self.head = joblib.load(head) if head.exists() else None
        self.meta = metadata or {}

    def _tensor(self, X: np.ndarray):
        torch = _torch()
        mean, std = self.norm
        return patchify(torch.from_numpy((X - mean) / std).float(), self.config["patch"])

    def _run(self, X: np.ndarray):
        torch = _torch()
        x = self._tensor(X)
        scores, maps = _window_scores(self.model, x, self.config, self.patch_bank, self.bank_k, self.ctx.device)
        embs = []
        self.model.eval()
        with torch.no_grad():
            for s in range(0, len(x), 256):
                embs.append(self.model.embed(x[s : s + 256].to(self.ctx.device)).cpu().numpy())
        return scores, np.concatenate(embs), maps

    def _band(self, patch: int) -> tuple[int, int]:
        """Sample index range of one patch of the (resampled) window."""
        size = int(self.config["patch"])
        return patch * size, min(int(self.config["T"]), (patch + 1) * size)

    def predict(self, ds: Dataset, mode: str, options: dict[str, Any], out: Path) -> PredictResult:
        out.mkdir(parents=True, exist_ok=True)
        X = as_windows(ds.X, self.config["T"])
        ids = ds.ids or [str(i) for i in range(len(X))]
        scores, emb, maps = self._run(X)
        if mode == "predict":
            if self.head is None:
                raise ValueError("此模型沒有迴歸頭，無法 predict；請用 score / embed / retrieve")
            pred = self.head.predict(emb)
            rows = [
                {"id": i, "prediction": float(p), "reconstruction_error": float(s)}
                for i, p, s in zip(ids, pred, scores, strict=True)
            ]
            return PredictResult(rows, {"mode": mode, "n": len(rows), "mean": float(pred.mean())})
        if mode == "embed":
            np.save(out / "embeddings.npy", emb)
            rows = [{"id": i, "embedding": [round(float(v), 6) for v in e]} for i, e in zip(ids, emb, strict=True)]
            art = ArtifactOut(name="embeddings", kind="report", path="output/embeddings.npy", framework="torch")
            return PredictResult(rows, {"mode": mode, "n": len(rows), "dim": int(emb.shape[1])}, [art])
        if mode == "retrieve":
            return self._retrieve(ids, emb, scores, options)
        threshold = float(options.get("threshold") or self.threshold or np.percentile(scores, 99))
        rows = []
        hot_bands: dict[str, int] = {}
        for i, s, m in zip(ids, scores, maps, strict=True):
            hot = int(np.argmax(m))
            start, end = self._band(hot)
            row = {
                "id": i,
                "anomaly_score": float(s),
                "is_anomaly": bool(s > threshold),
                "hot_patch": hot,
                "hot_band_start": start,
                "hot_band_end": end,
                "patch_scores": [round(float(v), 6) for v in m],
            }
            if row["is_anomaly"]:
                key = f"{start}-{end}"
                hot_bands[key] = hot_bands.get(key, 0) + 1
            rows.append(row)
        ranked = sorted(rows, key=lambda r: -r["anomaly_score"])[:20]
        return PredictResult(
            rows,
            {
                "mode": "score",
                "n": len(rows),
                "flagged": int(sum(r["is_anomaly"] for r in rows)),
                "threshold": threshold,
                "score_method": self.config.get("score_method", "recon"),
                "patch_size": int(self.config["patch"]),
                "window_length": int(self.config["T"]),
                "hot_bands": dict(sorted(hot_bands.items(), key=lambda kv: -kv[1])[:10]),
                "most_anomalous": [
                    {k: r[k] for k in ("id", "anomaly_score", "hot_band_start", "hot_band_end")} for r in ranked
                ],
            },
        )

    def _retrieve(self, ids: list[str], emb: np.ndarray, scores: np.ndarray, options: dict[str, Any]) -> PredictResult:
        k = int(options.get("k", 5))
        if options.get("reference") == "self":
            ref_emb, ref_ids = emb, np.asarray(ids)
        else:
            ref_emb, ref_ids = self.reference["embeddings"], self.reference["ids"]
        a = emb / (np.linalg.norm(emb, axis=1, keepdims=True) + 1e-9)
        b = ref_emb / (np.linalg.norm(ref_emb, axis=1, keepdims=True) + 1e-9)
        sims = a @ b.T  # (N, R)
        rows = []
        for n, i in enumerate(ids):
            s = sims[n].copy()
            if options.get("reference") == "self":
                s[n] = -np.inf
            order = np.argsort(-s)
            top = [j for j in order[:k] if np.isfinite(s[j])]
            bottom = [j for j in order[::-1][:k] if np.isfinite(s[j])]
            rows.append(
                {
                    "id": i,
                    "max_similarity": float(s[top[0]]) if top else None,
                    "novelty": float(1 - s[top[0]]) if top else None,
                    "most_similar": [{"id": str(ref_ids[j]), "similarity": round(float(s[j]), 5)} for j in top],
                    "least_similar": [{"id": str(ref_ids[j]), "similarity": round(float(s[j]), 5)} for j in bottom],
                    "reconstruction_error": float(scores[n]),
                }
            )
        by_novelty = sorted((r for r in rows if r["novelty"] is not None), key=lambda r: -r["novelty"])
        summary = {
            "mode": "retrieve",
            "n": len(rows),
            "k": k,
            "reference_size": len(ref_ids),
            "most_novel": [{"id": r["id"], "novelty": round(r["novelty"], 5)} for r in by_novelty[:20]],
            "most_typical": [
                {"id": r["id"], "max_similarity": round(r["max_similarity"], 5)} for r in by_novelty[::-1][:20]
            ],
        }
        return PredictResult(rows, summary)


class PatchAutoencoderInferencer(_SeqInferencer):
    pass


class SpectrumMAEInferencer(_SeqInferencer):
    pass
