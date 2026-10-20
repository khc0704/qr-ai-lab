"""Text family: BERT-style sequence classifier fine-tuned from a model-zoo folder (transformers, offline)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from trainer import jsonsafe
from trainer import metrics as M
from trainer.data.split import holdout
from trainer.dataset import Dataset
from trainer.log import info, warn
from trainer.models.base import ArtifactOut, BaseInferencer, BaseTrainer, PredictResult


class BertClassifierTrainer(BaseTrainer):
    framework = "transformers"
    inference_modes = ["predict", "embed"]

    def fit(self, ds: Dataset) -> None:
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        if not ds.has_labels:
            raise ValueError("文字分類需要標籤欄位（spec.label_column）")
        torch.manual_seed(int(self.params.get("seed", 42)))
        base_id = str(self.params.get("model", "bert-base-chinese"))
        base = self.ctx.weight(base_id)
        texts = [str(t) for t in ds.X]
        labels = np.asarray(ds.y).astype(str)
        self.classes = sorted(set(labels.tolist()))
        index = {c: i for i, c in enumerate(self.classes)}
        y = np.array([index[v] for v in labels])
        tr, va = holdout(len(texts), labels, "classification")
        max_len = int(self.params.get("max_len", 256))
        epochs = int(self.params.get("epochs", 3))
        batch = int(self.params.get("batch", 16))
        lr = float(self.params.get("lr", 2e-5))
        device = self.ctx.device
        self.tokenizer = AutoTokenizer.from_pretrained(str(base), local_files_only=True)
        self.model = AutoModelForSequenceClassification.from_pretrained(
            str(base), num_labels=len(self.classes), local_files_only=True
        ).to(device)
        info(
            f"bert: base={base_id} classes={len(self.classes)} train={len(tr)} val={len(va)} "
            f"max_len={max_len} device={device}"
        )

        def encode(idx):
            enc = self.tokenizer(
                [texts[i] for i in idx],
                truncation=True,
                max_length=max_len,
                padding=True,
                return_tensors="pt",
            )
            return enc, torch.tensor(y[idx])

        for attempt in range(2):
            try:
                self._train_loop(encode, tr, va, y, epochs, batch, lr, device)
                break
            except torch.cuda.OutOfMemoryError:
                if attempt == 1 or batch <= 1:
                    raise
                warn(f"bert: CUDA out of memory with batch={batch} → retrying with {batch // 2}")
                batch //= 2
                torch.cuda.empty_cache()
        self.meta.update({"classes": self.classes, "max_len": max_len, "base": base_id})

    def _train_loop(self, encode, tr, va, y, epochs: int, batch: int, lr: float, device: str) -> None:
        import torch

        opt = torch.optim.AdamW(self.model.parameters(), lr=lr, weight_decay=0.01)
        steps = epochs * max(1, int(np.ceil(len(tr) / batch)))
        sched = torch.optim.lr_scheduler.LambdaLR(
            opt, lambda s: min(1.0, (s + 1) / max(1, int(0.1 * steps))) * max(0.0, 1 - s / steps)
        )
        rng = np.random.default_rng(0)
        for epoch in range(1, epochs + 1):
            self.model.train()
            order = rng.permutation(tr)
            total = 0.0
            for s in range(0, len(order), batch):
                enc, yb = encode(order[s : s + batch])
                out = self.model(**{k: v.to(device) for k, v in enc.items()}, labels=yb.to(device))
                opt.zero_grad(set_to_none=True)
                out.loss.backward()
                torch.nn.utils.clip_grad_norm_(self.model.parameters(), 1.0)
                opt.step()
                sched.step()
                total += float(out.loss) * len(yb)
                self.ctx.progress(((epoch - 1) + (s + batch) / len(order)) / epochs, "training")
            preds, proba = self._predict_idx(encode, va, batch, device)
            self.metrics = M.classification(y[va], preds, proba)
            ep = {"loss": total / max(1, len(order)), **self.metrics}
            info(f"epoch {epoch}/{epochs} " + " ".join(f"{k}={v:.4f}" for k, v in ep.items()))
            self.ctx.epoch(epoch, ep)

    def _predict_idx(self, encode, idx, batch: int, device: str):
        import torch

        self.model.eval()
        probs = []
        with torch.no_grad():
            for s in range(0, len(idx), batch):
                enc, _ = encode(idx[s : s + batch])
                logits = self.model(**{k: v.to(device) for k, v in enc.items()}).logits
                probs.append(torch.softmax(logits, dim=-1).cpu().numpy())
        proba = np.concatenate(probs)
        return proba.argmax(axis=1), proba

    def export(self, out: Path) -> list[ArtifactOut]:
        model_dir = out / "model"
        model_dir.mkdir(parents=True, exist_ok=True)
        self.model.save_pretrained(model_dir / "bert")
        self.tokenizer.save_pretrained(model_dir / "bert")
        meta = {
            "classes": self.classes,
            "max_len": self.meta.get("max_len"),
            "base": self.meta.get("base"),
            "metrics": self.metrics,
        }
        (model_dir / "metadata.json").write_text(jsonsafe.dumps(meta, indent=2), encoding="utf-8")
        return [
            ArtifactOut(
                name="bert_classifier",
                kind="model",
                path="model",
                framework=self.framework,
                metrics=self.metrics,
                metadata=meta,
            )
        ]


class BertClassifierInferencer(BaseInferencer):
    def load(self, model_path: Path, metadata: dict[str, Any]) -> None:
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        local = model_path / "metadata.json"
        self.meta = {
            **(json.loads(local.read_text(encoding="utf-8")) if local.exists() else {}),
            **(metadata or {}),
        }
        self.classes: list[str] = list(self.meta.get("classes") or [])
        self.max_len = int(self.meta.get("max_len") or 256)
        self.tokenizer = AutoTokenizer.from_pretrained(str(model_path / "bert"), local_files_only=True)
        self.model = (
            AutoModelForSequenceClassification.from_pretrained(str(model_path / "bert"), local_files_only=True)
            .to(self.ctx.device)
            .eval()
        )

    def predict(self, ds: Dataset, mode: str, options: dict[str, Any], out: Path) -> PredictResult:
        out.mkdir(parents=True, exist_ok=True)
        import torch

        texts = [str(t) for t in ds.X]
        ids = ds.ids or [str(i) for i in range(len(texts))]
        batch = int(options.get("batch", 32))
        rows: list[dict[str, Any]] = []
        embs = []
        with torch.no_grad():
            for s in range(0, len(texts), batch):
                enc = self.tokenizer(
                    texts[s : s + batch],
                    truncation=True,
                    max_length=self.max_len,
                    padding=True,
                    return_tensors="pt",
                )
                enc = {k: v.to(self.ctx.device) for k, v in enc.items()}
                out_ = self.model(**enc, output_hidden_states=(mode == "embed"))
                if mode == "embed":
                    embs.append(out_.hidden_states[-1][:, 0].cpu().numpy())
                else:
                    proba = torch.softmax(out_.logits, dim=-1).cpu().numpy()
                    for k, p in enumerate(proba):
                        j = int(p.argmax())
                        row = {
                            "id": ids[s + k],
                            "prediction": self.classes[j] if j < len(self.classes) else str(j),
                            "confidence": float(p[j]),
                        }
                        if len(self.classes) <= 50:
                            row.update({f"proba_{c}": float(p[i]) for i, c in enumerate(self.classes)})
                        rows.append(row)
                self.ctx.progress(min(1.0, (s + batch) / max(1, len(texts))))
        if mode == "embed":
            emb = np.concatenate(embs)
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
        counts: dict[str, int] = {}
        for r in rows:
            counts[r["prediction"]] = counts.get(r["prediction"], 0) + 1
        return PredictResult(rows, {"mode": "predict", "n": len(rows), "class_counts": counts})


# -- Qwen3 embedding: frozen encoder + reference bank (+ a linear head when labels exist) ------------------------

QWEN_DEFAULT = "qwen3-embedding-0.6b"
NOVELTY_PERCENTILE = 99


QWEN_POOLS = ("last_token", "mean")
QWEN_LAYERS = ("last", "last4")


class _QwenEncoder:
    """Frozen Qwen3-Embedding from the zoo, L2-normalised vectors. ``pool``: ``last_token`` (what the model was
    trained for) or ``mean`` over the real tokens (more robust on long, list-like logs); ``layers``: ``last``
    hidden state or the mean of the ``last4`` (slightly more lexical, helps near-duplicate retrieval).
    Documents are embedded as-is; a query-side ``instruction`` ("Instruct: …\\nQuery: …") is only used when
    the user asks for it."""

    def __init__(
        self, ctx, model_id: str, max_len: int, batch: int, pool: str = "last_token", layers: str = "last"
    ) -> None:
        import torch
        from transformers import AutoModel, AutoTokenizer

        if pool not in QWEN_POOLS:
            raise ValueError(f"pool 必須是 {' / '.join(QWEN_POOLS)}，不是 {pool!r}")
        if layers not in QWEN_LAYERS:
            raise ValueError(f"layers 必須是 {' / '.join(QWEN_LAYERS)}，不是 {layers!r}")
        path = ctx.weight(model_id)
        self.ctx = ctx
        self.torch = torch
        self.tokenizer = AutoTokenizer.from_pretrained(str(path), local_files_only=True)
        self.model = AutoModel.from_pretrained(str(path), local_files_only=True).to(ctx.device).eval()
        self.max_len = max_len
        self.batch = batch
        self.pool = pool
        self.layers = layers
        self.dim = int(self.model.config.hidden_size)
        info(
            f"qwen: loaded {model_id} from {path} on {ctx.device} (dim={self.dim}, max_len={max_len}, "
            f"pool={pool}, layers={layers})"
        )

    def encode(self, texts: list[str], instruction: str | None = None, progress=None) -> np.ndarray:
        torch = self.torch
        if instruction:
            texts = [f"Instruct: {instruction}\nQuery: {t}" for t in texts]
        out = []
        with torch.no_grad():
            for s in range(0, len(texts), self.batch):
                enc = self.tokenizer(
                    texts[s : s + self.batch],
                    truncation=True,
                    max_length=self.max_len,
                    padding=True,
                    return_tensors="pt",
                ).to(self.ctx.device)
                res = self.model(**enc, output_hidden_states=self.layers != "last")
                h = torch.stack(res.hidden_states[-4:]).mean(dim=0) if self.layers == "last4" else res.last_hidden_state
                mask = enc["attention_mask"]
                if self.pool == "mean":
                    m = mask[:, :, None].to(h.dtype)
                    pooled = (h * m).sum(dim=1) / m.sum(dim=1).clamp(min=1)
                elif bool((mask[:, -1] == 1).all()):  # left padding: the last position is the last real token
                    pooled = h[:, -1]
                else:
                    last = mask.sum(dim=1) - 1
                    pooled = h[torch.arange(h.shape[0], device=h.device), last]
                pooled = torch.nn.functional.normalize(pooled.float(), dim=-1)
                out.append(pooled.cpu().numpy().astype(np.float32))
                if progress:
                    progress(min(1.0, (s + self.batch) / max(1, len(texts))))
        return np.concatenate(out) if out else np.zeros((0, self.dim), np.float32)


def _novelty(emb: np.ndarray, bank: np.ndarray, exclude_self: bool = False) -> np.ndarray:
    """1 − max cosine similarity to the bank (rows are unit vectors)."""
    sims = emb @ bank.T
    if exclude_self:
        np.fill_diagonal(sims, -np.inf)
    best = sims.max(axis=1)
    best = np.where(np.isfinite(best), best, 1.0)
    return 1.0 - best


class QwenEmbeddingTrainer(BaseTrainer):
    framework = "transformers"

    def __init__(self, family: str, task: str | None, params: dict[str, Any], ctx) -> None:
        super().__init__(family, task, params, ctx)
        self.inference_modes = (
            ["score", "retrieve", "embed"] if task == "anomaly_detection" else ["predict", "retrieve", "embed"]
        )
        self.head = None
        self.classes: list[str] | None = None
        self.threshold: float | None = None

    def fit(self, ds: Dataset) -> None:
        from trainer.models.tabular import _binary_anomaly_labels

        base_id = str(self.params.get("model", QWEN_DEFAULT))
        max_len = int(self.params.get("max_len", 512))
        batch = int(self.params.get("batch", 16))
        texts = [str(t) for t in ds.X]
        ids = [str(i) for i in (ds.ids or range(len(texts)))]
        pool = str(self.params.get("pool") or "last_token")
        layers = str(self.params.get("layers") or "last")
        self.encoder = _QwenEncoder(self.ctx, base_id, max_len, batch, pool=pool, layers=layers)
        self.ctx.progress(0.05, "training")
        emb = self.encoder.encode(texts, progress=lambda f: self.ctx.progress(0.05 + 0.7 * f, "training"))
        self.instruction = str(self.params.get("instruction") or "")
        if self.task == "anomaly_detection":
            y = _binary_anomaly_labels(ds.y) if ds.has_labels else None
            self._fit_anomaly(emb, y)
            keep = np.flatnonzero(y == 0) if y is not None else np.arange(len(emb))
            self.bank, self.bank_ids = emb[keep], np.asarray([ids[i] for i in keep])
            self.bank_labels = np.asarray(["normal"] * len(keep))
        else:
            if not ds.has_labels:
                raise ValueError("文字分類需要標籤欄位（spec.label_column）")
            labels = np.asarray(ds.y).astype(str)
            self.classes = sorted(set(labels.tolist()))
            index = {c: i for i, c in enumerate(self.classes)}
            y = np.array([index[v] for v in labels])
            tr, va = holdout(len(texts), labels, "classification")
            self.head = self._head().fit(emb[tr], y[tr])
            proba = self.head.predict_proba(emb[va])
            self.metrics = M.classification(y[va], proba.argmax(axis=1), proba)
            self.bank, self.bank_ids, self.bank_labels = emb, np.asarray(ids), labels
            self._emb, self._y = emb, y
        self.meta.update(
            {
                "base": base_id,
                "max_len": max_len,
                "dim": int(emb.shape[1]),
                "instruction": self.instruction,
                "pool": pool,
                "layers": layers,
            }
        )
        info(f"{self.family}: " + ", ".join(f"{k}={v:.4f}" for k, v in self.metrics.items()))
        self.ctx.progress(0.9, "evaluating")

    def _head(self):
        from sklearn.linear_model import LogisticRegression

        return LogisticRegression(C=float(self.params.get("C", 1.0)), max_iter=3000)

    def _fit_anomaly(self, emb: np.ndarray, y: np.ndarray | None) -> None:
        if y is not None and set(np.unique(y).tolist()) == {0, 1}:
            normal = np.flatnonzero(y == 0)
            tr, va_n = holdout(len(normal), None, None)
            bank = emb[normal[tr]]
            val_idx = np.concatenate([normal[va_n], np.flatnonzero(y == 1)])
            self.threshold = float(np.percentile(_novelty(bank, bank, exclude_self=True), NOVELTY_PERCENTILE))
            self.metrics = M.anomaly(_novelty(emb[val_idx], bank), y[val_idx], self.threshold)
        else:
            scores = _novelty(emb, emb, exclude_self=True)
            self.threshold = float(np.percentile(scores, NOVELTY_PERCENTILE))
            self.metrics = M.anomaly(scores, None, self.threshold)
        self.meta["threshold"] = self.threshold

    def finalize(self, ds: Dataset) -> None:
        if self.head is not None:
            self.head = self._head().fit(self._emb, self._y)

    def export(self, out: Path) -> list[ArtifactOut]:
        import joblib

        model_dir = out / "model"
        model_dir.mkdir(parents=True, exist_ok=True)
        np.savez(
            model_dir / "reference.npz",
            embeddings=self.bank.astype(np.float32),
            ids=self.bank_ids.astype(str),
            labels=self.bank_labels.astype(str),
        )
        if self.head is not None:
            joblib.dump(self.head, model_dir / "head.joblib")
        meta = {
            "classes": self.classes,
            "threshold": self.threshold,
            "task_type": self.task,
            "inference_modes": self.inference_modes,
            "metrics": self.metrics,
            **self.meta,
        }
        (model_dir / "metadata.json").write_text(jsonsafe.dumps(meta, indent=2), encoding="utf-8")
        return [
            ArtifactOut(
                name="qwen_embedding",
                kind="model",
                path="model",
                framework=self.framework,
                metrics=self.metrics,
                metadata=meta,
            )
        ]


class QwenEmbeddingInferencer(BaseInferencer):
    def load(self, model_path: Path, metadata: dict[str, Any]) -> None:
        import joblib

        local = model_path / "metadata.json"
        self.meta = {
            **(json.loads(local.read_text(encoding="utf-8")) if local.exists() else {}),
            **(metadata or {}),
        }
        self.classes: list[str] = list(self.meta.get("classes") or [])
        self.task = self.meta.get("task_type")
        ref = np.load(model_path / "reference.npz", allow_pickle=False)
        self.bank = ref["embeddings"].astype(np.float32)
        self.bank_ids = ref["ids"].astype(str)
        self.bank_labels = ref["labels"].astype(str)
        head = model_path / "head.joblib"
        self.head = joblib.load(head) if head.exists() else None
        self.encoder = _QwenEncoder(
            self.ctx,
            str(self.meta.get("base", QWEN_DEFAULT)),
            int(self.meta.get("max_len") or 512),
            int(self.meta.get("batch") or 16),
            pool=str(self.meta.get("pool") or "last_token"),
            layers=str(self.meta.get("layers") or "last"),
        )

    def predict(self, ds: Dataset, mode: str, options: dict[str, Any], out: Path) -> PredictResult:
        from trainer.retrieval import neighbour_rows, parse_order

        out.mkdir(parents=True, exist_ok=True)
        texts = [str(t) for t in ds.X]
        ids = [str(i) for i in (ds.ids or range(len(texts)))]
        instruction = options.get("instruction")
        if instruction is None and mode == "retrieve":
            instruction = self.meta.get("instruction") or None
        emb = self.encoder.encode(texts, instruction=instruction, progress=lambda f: self.ctx.progress(0.9 * f))
        if mode == "embed":
            np.save(out / "embeddings.npy", emb)
            rows = [{"id": i, "embedding": [round(float(v), 6) for v in e]} for i, e in zip(ids, emb, strict=True)]
            art = ArtifactOut(name="embeddings", kind="report", path="output/embeddings.npy", framework="torch")
            return PredictResult(rows, {"mode": mode, "n": len(rows), "dim": int(emb.shape[1])}, [art])
        if mode == "retrieve":
            order = parse_order(options, "both")
            k = int(options.get("k", 5))
            if options.get("reference") == "self":
                ref_emb, ref_ids, ref_labels = emb, np.asarray(ids), None
            else:
                ref_emb, ref_ids, ref_labels = self.bank, self.bank_ids, self.bank_labels
            sims = emb @ ref_emb.T
            if options.get("reference") == "self":
                np.fill_diagonal(sims, np.nan)
            rows = [{"id": i, **neighbour_rows(sims[n], order, k, ref_labels, ref_ids)} for n, i in enumerate(ids)]
            novel = sorted((r for r in rows if r["max_similarity"] is not None), key=lambda r: r["max_similarity"])
            return PredictResult(
                rows,
                {
                    "mode": mode,
                    "n": len(rows),
                    "k": k,
                    "order": order,
                    "reference_size": len(ref_ids),
                    "most_novel": [
                        {"id": r["id"], "max_similarity": round(r["max_similarity"], 5)} for r in novel[:20]
                    ],
                },
            )
        if mode == "score" or self.task == "anomaly_detection":
            scores = _novelty(emb, self.bank)
            threshold = float(options.get("threshold") or self.meta.get("threshold") or np.percentile(scores, 99))
            rows = [
                {"id": i, "anomaly_score": float(s), "is_anomaly": bool(s > threshold)}
                for i, s in zip(ids, scores, strict=True)
            ]
            flagged = int(sum(r["is_anomaly"] for r in rows))
            return PredictResult(rows, {"mode": "score", "n": len(rows), "flagged": flagged, "threshold": threshold})
        if self.head is None:
            raise ValueError("此模型沒有分類頭，無法 predict；請用 retrieve / embed")
        proba = self.head.predict_proba(emb)
        reject = options.get("min_confidence")
        rows = []
        for n, i in enumerate(ids):
            j = int(proba[n].argmax())
            row = {
                "id": i,
                "prediction": self.classes[j] if j < len(self.classes) else str(j),
                "confidence": float(proba[n][j]),
            }
            if reject is not None and row["confidence"] < float(reject):
                row["prediction"] = "unknown"
            if len(self.classes) <= 50:
                row.update({f"proba_{c}": float(proba[n][m]) for m, c in enumerate(self.classes)})
            rows.append(row)
        counts: dict[str, int] = {}
        for r in rows:
            counts[r["prediction"]] = counts.get(r["prediction"], 0) + 1
        return PredictResult(rows, {"mode": "predict", "n": len(rows), "class_counts": counts})
