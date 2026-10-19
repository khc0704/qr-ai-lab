"""vision.image_quality — no-reference image quality baseline for tool matching.

Train on the golden tool's images: compute a vector of classic IQA metrics per image (sharpness, noise, contrast,
brightness, clipping, entropy, spectral content, directional anisotropy), and store the baseline (robust mean / std
per metric, allowed range, covariance for Mahalanobis distance, the golden metric matrix for KS tests).

Inference:
  score   → per image: metrics, z-score per metric, Mahalanobis distance, out-of-range metrics, verdict
  compare → the whole input set vs the baseline: per-metric effect size + KS test + verdict (tool matching report)
  embed   → the metric vector per image
No GPU, no pretrained weights; works on SEM / TEM / optical images alike.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image
from scipy import ndimage, stats

from trainer import jsonsafe
from trainer import metrics as M
from trainer.data.split import holdout
from trainer.dataset import Dataset
from trainer.log import info, warn
from trainer.models.base import ArtifactOut, BaseInferencer, BaseTrainer, PredictResult
from trainer.models.tabular import _binary_anomaly_labels

METRICS: list[str] = [
    "sharpness_laplacian",
    "sharpness_tenengrad",
    "sharpness_brenner",
    "noise_sigma",
    "snr",
    "contrast_rms",
    "contrast_michelson",
    "brightness_mean",
    "brightness_p01",
    "brightness_p99",
    "clip_low_ratio",
    "clip_high_ratio",
    "entropy",
    "hf_energy_ratio",
    "spectral_slope",
    "anisotropy_gradient",
    "anisotropy_fft",
]
LABELS = {
    "sharpness_laplacian": "清晰度（Laplacian 變異）",
    "sharpness_tenengrad": "清晰度（Tenengrad）",
    "sharpness_brenner": "清晰度（Brenner）",
    "noise_sigma": "雜訊標準差",
    "snr": "訊噪比",
    "contrast_rms": "對比（RMS）",
    "contrast_michelson": "對比（Michelson）",
    "brightness_mean": "平均亮度",
    "brightness_p01": "亮度 P1",
    "brightness_p99": "亮度 P99",
    "clip_low_ratio": "過暗飽和比例",
    "clip_high_ratio": "過亮飽和比例",
    "entropy": "亮度熵",
    "hf_energy_ratio": "高頻能量比",
    "spectral_slope": "頻譜斜率",
    "anisotropy_gradient": "方向性（梯度 x/y）",
    "anisotropy_fft": "方向性（頻譜 水平/垂直）",
}
MAX_SIDE = 1024


def image_metrics(im: Image.Image) -> dict[str, float]:
    g = im.convert("L")
    if max(g.size) > MAX_SIDE:
        g.thumbnail((MAX_SIDE, MAX_SIDE))
    a = np.asarray(g, dtype=np.float32)
    h, w = a.shape
    out: dict[str, float] = {}
    lap = ndimage.laplace(a)
    out["sharpness_laplacian"] = float(lap.var())
    sx, sy = ndimage.sobel(a, axis=1), ndimage.sobel(a, axis=0)
    gx2, gy2 = float((sx**2).mean()), float((sy**2).mean())
    out["sharpness_tenengrad"] = gx2 + gy2
    out["sharpness_brenner"] = float(((a[:, 2:] - a[:, :-2]) ** 2).mean()) if w > 2 else 0.0
    # Immerkær fast noise estimate
    kernel = np.array([[1, -2, 1], [-2, 4, -2], [1, -2, 1]], dtype=np.float32)
    conv = ndimage.convolve(a, kernel, mode="reflect")
    sigma = float(np.sqrt(np.pi / 2) * np.abs(conv).sum() / (6.0 * max(1, (w - 2) * (h - 2))))
    out["noise_sigma"] = sigma
    out["snr"] = float(a.mean() / (sigma + 1e-6))
    p01, p99 = np.percentile(a, [1, 99])
    out["contrast_rms"] = float(a.std())
    out["contrast_michelson"] = float((p99 - p01) / (p99 + p01 + 1e-6))
    out["brightness_mean"] = float(a.mean())
    out["brightness_p01"] = float(p01)
    out["brightness_p99"] = float(p99)
    out["clip_low_ratio"] = float((a <= 1).mean())
    out["clip_high_ratio"] = float((a >= 254).mean())
    hist = np.bincount(a.astype(np.uint8).ravel(), minlength=256).astype(np.float64)
    p = hist / max(1.0, hist.sum())
    p = p[p > 0]
    out["entropy"] = float(-(p * np.log2(p)).sum())
    # spectrum: radial power, high-frequency share, log-log slope, horizontal / vertical anisotropy
    f = np.fft.fftshift(np.fft.fft2(a - a.mean()))
    power = np.abs(f) ** 2
    cy, cx = h // 2, w // 2
    yy, xx = np.indices(power.shape)
    r = np.sqrt(((yy - cy) / max(1, h)) ** 2 + ((xx - cx) / max(1, w)) ** 2)  # 0 … ~0.71, Nyquist = 0.5
    total = float(power.sum()) + 1e-9
    out["hf_energy_ratio"] = float(power[r > 0.25].sum() / total)
    band = (r > 0.02) & (r < 0.45)
    if band.sum() > 10:
        rb, pb = r[band], power[band] + 1e-9
        bins = np.linspace(0.02, 0.45, 24)
        idx = np.digitize(rb, bins)
        xs, ys = [], []
        for b in range(1, len(bins)):
            sel = idx == b
            if sel.any():
                xs.append(np.log(bins[b - 1 : b + 1].mean()))
                ys.append(np.log(pb[sel].mean()))
        out["spectral_slope"] = float(np.polyfit(xs, ys, 1)[0]) if len(xs) > 3 else 0.0
    else:
        out["spectral_slope"] = 0.0
    out["anisotropy_gradient"] = float(np.log((gx2 + 1e-6) / (gy2 + 1e-6)))
    ang = np.arctan2(yy - cy, xx - cx)
    horiz = (np.abs(np.cos(ang)) > np.cos(np.pi / 8)) & (r > 0.02)
    vert = (np.abs(np.sin(ang)) > np.cos(np.pi / 8)) & (r > 0.02)
    out["anisotropy_fft"] = float(np.log((power[horiz].sum() + 1e-6) / (power[vert].sum() + 1e-6)))
    return out


def metric_matrix(paths: list[Path], progress=None) -> np.ndarray:
    rows = []
    for k, p in enumerate(paths):
        with Image.open(p) as im:
            m = image_metrics(im)
        rows.append([m[name] for name in METRICS])
        if progress and (k % 10 == 0 or k == len(paths) - 1):
            progress((k + 1) / max(1, len(paths)))
    return np.asarray(rows, dtype=np.float64)


class Baseline:
    """Robust per-metric statistics + Mahalanobis distance learned from the golden image set."""

    def __init__(self, matrix: np.ndarray, z_threshold: float, distance_percentile: float) -> None:
        self.matrix = matrix
        self.n = len(matrix)
        self.median = np.median(matrix, axis=0)
        mad = np.median(np.abs(matrix - self.median), axis=0) * 1.4826
        std = matrix.std(axis=0)
        self.scale = np.where(mad > 1e-9, mad, np.where(std > 1e-9, std, 1.0))
        self.mean = matrix.mean(axis=0)
        self.std = np.where(std > 1e-9, std, 1.0)
        self.z_threshold = z_threshold
        z = (matrix - self.median) / self.scale
        cov = np.cov(z, rowvar=False) if self.n > 2 else np.eye(len(METRICS))
        cov = np.atleast_2d(cov) + np.eye(len(METRICS)) * 1e-3
        self.precision = np.linalg.pinv(cov)
        d = self.distances(matrix)
        self.threshold = float(max(np.percentile(d, distance_percentile), 1e-6))
        self.low = self.median - z_threshold * self.scale
        self.high = self.median + z_threshold * self.scale

    def zscores(self, matrix: np.ndarray) -> np.ndarray:
        return (matrix - self.median) / self.scale

    def distances(self, matrix: np.ndarray) -> np.ndarray:
        z = self.zscores(matrix)
        return np.sqrt(np.einsum("ij,jk,ik->i", z, self.precision, z).clip(min=0))

    def to_json(self) -> dict[str, Any]:
        return {
            "metrics": METRICS,
            "n": self.n,
            "median": self.median.tolist(),
            "scale": self.scale.tolist(),
            "mean": self.mean.tolist(),
            "std": self.std.tolist(),
            "low": self.low.tolist(),
            "high": self.high.tolist(),
            "precision": self.precision.tolist(),
            "threshold": self.threshold,
            "z_threshold": self.z_threshold,
            "golden": self.matrix.round(6).tolist(),
        }

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> Baseline:
        obj = cls.__new__(cls)
        obj.matrix = np.asarray(d["golden"], dtype=np.float64)
        obj.n = int(d["n"])
        obj.median = np.asarray(d["median"])
        obj.scale = np.asarray(d["scale"])
        obj.mean = np.asarray(d["mean"])
        obj.std = np.asarray(d["std"])
        obj.low = np.asarray(d["low"])
        obj.high = np.asarray(d["high"])
        obj.precision = np.asarray(d["precision"])
        obj.threshold = float(d["threshold"])
        obj.z_threshold = float(d["z_threshold"])
        return obj


class ImageQualityTrainer(BaseTrainer):
    framework = "numpy"
    inference_modes = ["compare", "score", "embed"]

    def fit(self, ds: Dataset) -> None:
        z_thr = float(self.params.get("z_threshold", 3.0))
        pct = float(self.params.get("distance_percentile", 99))
        paths = list(ds.X)
        y = _binary_anomaly_labels(ds.y) if ds.has_labels else None
        golden_idx = np.flatnonzero(y == 0) if y is not None else np.arange(len(paths))
        if len(golden_idx) < 5:
            raise ValueError("需要至少 5 張黃金機台（good / normal 資料夾）影像")
        if len(golden_idx) < 20:
            warn(f"只有 {len(golden_idx)} 張基準影像，浮動範圍會不穩定（建議 ≥ 30）")
        self.ctx.progress(0.05, "training")
        matrix = metric_matrix(paths, progress=lambda f: self.ctx.progress(0.05 + 0.8 * f, "training"))
        tr, va = holdout(len(golden_idx), None, None)
        fit_idx = golden_idx[tr]
        self.baseline = Baseline(matrix[fit_idx], z_thr, pct)
        val_idx = np.concatenate([golden_idx[va], np.flatnonzero(y == 1)]) if y is not None else golden_idx[va]
        d = self.baseline.distances(matrix[val_idx])
        labels = y[val_idx] if (y is not None and len(np.unique(y[val_idx])) == 2) else None
        self.metrics = M.anomaly(d, labels, self.baseline.threshold)
        self.metrics["n_golden"] = float(len(golden_idx))
        # final baseline uses every golden image
        self.baseline = Baseline(matrix[golden_idx], z_thr, pct)
        self.ids = [ds.ids[i] for i in golden_idx]
        self.meta.update({"threshold": self.baseline.threshold, "z_threshold": z_thr, "n_golden": len(golden_idx)})
        info(f"{self.family}: " + ", ".join(f"{k}={v:.4f}" for k, v in self.metrics.items()))

    def export(self, out: Path) -> list[ArtifactOut]:
        model_dir = out / "model"
        model_dir.mkdir(parents=True, exist_ok=True)
        (model_dir / "baseline.json").write_text(json.dumps(self.baseline.to_json()), encoding="utf-8")
        meta = {"threshold": self.baseline.threshold, "z_threshold": self.baseline.z_threshold, "metrics": self.metrics}
        (model_dir / "metadata.json").write_text(jsonsafe.dumps(meta, indent=2), encoding="utf-8")
        rep = out / "report"
        rep.mkdir(parents=True, exist_ok=True)
        with (rep / "baseline_ranges.csv").open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["metric", "label", "median", "scale", "low", "high", "mean", "std"])
            b = self.baseline
            for i, name in enumerate(METRICS):
                w.writerow([name, LABELS[name], b.median[i], b.scale[i], b.low[i], b.high[i], b.mean[i], b.std[i]])
        with (rep / "baseline_metrics.csv").open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["id", *METRICS])
            for i, row in zip(self.ids, self.baseline.matrix, strict=True):
                w.writerow([i, *row])
        return [
            ArtifactOut(
                name="image_quality_baseline",
                kind="model",
                path="model",
                framework=self.framework,
                metrics=self.metrics,
                metadata=meta,
            ),
            ArtifactOut(
                name="baseline_ranges", kind="report", path="report/baseline_ranges.csv", framework=self.framework
            ),
            ArtifactOut(
                name="baseline_metrics", kind="report", path="report/baseline_metrics.csv", framework=self.framework
            ),
        ]


class ImageQualityInferencer(BaseInferencer):
    def load(self, model_path: Path, metadata: dict[str, Any]) -> None:
        self.baseline = Baseline.from_json(json.loads((model_path / "baseline.json").read_text(encoding="utf-8")))
        self.meta = metadata or {}

    def predict(self, ds: Dataset, mode: str, options: dict[str, Any], out: Path) -> PredictResult:
        out.mkdir(parents=True, exist_ok=True)
        paths = list(ds.X)
        ids = ds.ids or [Path(p).name for p in paths]
        matrix = metric_matrix(paths, progress=lambda f: self.ctx.progress(0.9 * f))
        if mode == "embed":
            rows = [
                {"id": i, "embedding": [round(float(v), 6) for v in row]} for i, row in zip(ids, matrix, strict=True)
            ]
            return PredictResult(rows, {"mode": mode, "n": len(rows), "metrics": METRICS})
        b = self.baseline
        z_thr = float(options.get("z_threshold") or b.z_threshold)
        threshold = float(options.get("threshold") or b.threshold)
        z = b.zscores(matrix)
        d = b.distances(matrix)
        rows = []
        for k, i in enumerate(ids):
            row: dict[str, Any] = {"id": i, "distance": float(d[k]), "is_anomaly": bool(d[k] > threshold)}
            oor = [METRICS[j] for j in range(len(METRICS)) if abs(z[k, j]) > z_thr]
            row["out_of_range"] = oor
            for j, name in enumerate(METRICS):
                row[name] = float(matrix[k, j])
                row[f"z_{name}"] = float(z[k, j])
            rows.append(row)
        summary: dict[str, Any] = {
            "mode": mode,
            "n": len(rows),
            "threshold": threshold,
            "z_threshold": z_thr,
            "flagged": int(sum(r["is_anomaly"] for r in rows)),
            "distance_median": float(np.median(d)),
            "baseline_distance_threshold": b.threshold,
        }
        extra: list[ArtifactOut] = []
        if mode == "compare":
            table = self._compare(matrix, options)
            summary.update(table["summary"])
            summary["per_metric"] = table["per_metric"]
            (out / "comparison.json").write_text(jsonsafe.dumps(table, indent=2), encoding="utf-8")
            with (out / "comparison.csv").open("w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=list(table["per_metric"][0].keys()))
                w.writeheader()
                w.writerows(table["per_metric"])
            extra.append(
                ArtifactOut(name="tool_matching_report", kind="report", path="output/comparison.csv", framework="numpy")
            )
        return PredictResult(rows, summary, extra)

    def _compare(self, matrix: np.ndarray, options: dict[str, Any]) -> dict[str, Any]:
        """Set-level comparison: effect size (in golden robust-std units) and KS test per metric."""
        b = self.baseline
        effect_warn = float(options.get("effect_warn", 1.0))
        effect_fail = float(options.get("effect_fail", 2.0))
        alpha = float(options.get("alpha", 0.01))
        per_metric = []
        n_match = 0
        for j, name in enumerate(METRICS):
            test = matrix[:, j]
            golden = b.matrix[:, j]
            effect = float((np.median(test) - b.median[j]) / b.scale[j])
            try:
                ks = stats.ks_2samp(golden, test)
                ks_stat, p = float(ks.statistic), float(ks.pvalue)
            except ValueError:
                ks_stat, p = 0.0, 1.0
            in_range = float(((test >= b.low[j]) & (test <= b.high[j])).mean())
            if abs(effect) >= effect_fail:
                verdict = "fail"
            elif abs(effect) >= effect_warn or (p < alpha and len(test) >= 8):
                verdict = "drift"
            else:
                verdict = "match"
                n_match += 1
            per_metric.append(
                {
                    "metric": name,
                    "label": LABELS[name],
                    "golden_median": float(b.median[j]),
                    "golden_low": float(b.low[j]),
                    "golden_high": float(b.high[j]),
                    "test_median": float(np.median(test)),
                    "test_std": float(test.std()),
                    "effect": effect,
                    "ks_statistic": ks_stat,
                    "p_value": p,
                    "in_range_ratio": in_range,
                    "verdict": verdict,
                }
            )
        fails = [m["metric"] for m in per_metric if m["verdict"] == "fail"]
        drifts = [m["metric"] for m in per_metric if m["verdict"] == "drift"]
        overall = "fail" if fails else ("drift" if drifts else "pass")
        return {
            "summary": {
                "verdict": overall,
                "matched_metrics": n_match,
                "total_metrics": len(METRICS),
                "match_ratio": n_match / len(METRICS),
                "failed_metrics": fails,
                "drifted_metrics": drifts,
                "n_test": len(matrix),
                "n_golden": int(b.n),
            },
            "per_metric": per_metric,
        }
