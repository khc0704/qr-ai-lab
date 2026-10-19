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
