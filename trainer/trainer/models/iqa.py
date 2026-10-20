"""vision.image_quality — image-quality baseline for tool matching (no-reference + optional full-reference).

Train on the golden tool's images: compute a vector of classic IQA metrics per image (sharpness, noise, contrast,
brightness, clipping, entropy, spectral content, directional anisotropy), and store the baseline (robust mean / std
per metric, allowed range, covariance for Mahalanobis distance, the golden metric matrix for KS tests).

Inference:
  score   → per image: metrics, z-score per metric, Mahalanobis distance, out-of-range metrics, verdict, the
            tile map of the metric that deviates most (``map``: a heat overlay, red = where the deviation
            concentrates) and ``advice`` (which knob to touch: focus / stigmator / brightness / noise …)
  compare → the whole input set vs the baseline: per-metric effect size + KS test + verdict (tool matching
            report) + per-aspect advice. With a reference folder (``golden/``, ``reference/`` …) holding the
            same file names as the other folder(s), each pair also gets full-reference metrics (phase-correlation
            alignment, PSNR, SSIM, MS-SSIM, GMSD) and an SSIM difference overlay.
  embed   → the metric vector per image
No GPU, no pretrained weights; works on SEM / TEM / optical images alike.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path, PurePosixPath
from typing import Any

import numpy as np
from PIL import Image
from scipy import ndimage, stats

from trainer import jsonsafe, viz
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

# Every metric belongs to one "aspect" = the knob on the tool that moves it. ``polarity`` says whether the metric
# grows with the aspect's tile value (+1) or against it (−1: a high SNR means little noise), so a z-score on any
# metric can be turned into "the aspect is too high / too low" and into a tile map of where it concentrates.
ASPECTS: dict[str, dict[str, Any]] = {
    "focus": {
        "label": "對焦 / 清晰度",
        "tile": "sharpness",
        "metrics": {
            "sharpness_laplacian": 1,
            "sharpness_tenengrad": 1,
            "sharpness_brenner": 1,
            "hf_energy_ratio": 1,
            "spectral_slope": 1,
        },
    },
    "noise": {"label": "雜訊", "tile": "noise", "metrics": {"noise_sigma": 1, "snr": -1}},
    "brightness": {
        "label": "亮度",
        "tile": "brightness",
        "metrics": {
            "brightness_mean": 1,
            "brightness_p01": 1,
            "brightness_p99": 1,
            "clip_high_ratio": 1,
            "clip_low_ratio": -1,
        },
    },
    "contrast": {
        "label": "對比",
        "tile": "contrast",
        "metrics": {"contrast_rms": 1, "contrast_michelson": 1, "entropy": 1},
    },
    "anisotropy": {
        "label": "方向性 / 像散",
        "tile": "anisotropy",
        "metrics": {"anisotropy_gradient": 1, "anisotropy_fft": 1},
    },
}
ASPECT_OF: dict[str, str] = {m: a for a, d in ASPECTS.items() for m in d["metrics"]}
ADVICE: dict[tuple[str, str], str] = {
    ("focus", "low"): (
        "比基準模糊：重新對焦（focus / working distance）、校正像散（stigmator），確認樣品高度與傾斜；"
        "整張一致模糊多半是對焦，局部模糊常是樣品不平或帶電。"
    ),
    ("focus", "high"): (
        "比基準更銳利、高頻更多：確認掃描解析度 / pixel size、放大倍率與銳化設定是否與黃金機台相同；"
        "若雜訊同時偏高，多半是 dwell time 變短。"
    ),
    ("noise", "high"): (
        "雜訊比基準高：拉長 dwell time 或增加積分 / 平均次數，確認束流、偵測器增益與真空度，排除接地與振動干擾。"
    ),
    ("noise", "low"): ("雜訊比基準低：確認是否套了平滑 / 降噪，或 dwell time、積分次數與黃金機台不同（基準需一致）。"),
    ("brightness", "high"): (
        "比基準亮：調低 brightness / offset 或偵測器增益；過亮飽和比例高時先降 contrast 再調亮度。"
    ),
    ("brightness", "low"): (
        "比基準暗：調高 brightness / offset 或增益，確認束流與偵測器狀態；過暗飽和多時先拉高黑階。"
    ),
    ("contrast", "high"): ("對比比基準強：調低 contrast / 增益，檢查是否過度拉伸造成兩端飽和、直方圖是否被截。"),
    ("contrast", "low"): ("對比比基準弱：調高 contrast，確認偵測器型式與樣品帶電（charging）狀況，必要時清潔光圈。"),
    ("anisotropy", "high"): (
        "方向性與基準不同（垂直邊緣較清楚、水平較糊或相反）：常見為像散（stigmator X / Y）未校正、"
        "掃描方向 / 掃描速度不同或樣品漂移；請用高倍下的圓形特徵重新校正像散。"
    ),
}
ADVICE[("anisotropy", "low")] = ADVICE[("anisotropy", "high")]
MAP_MAX = 2000  # overlays written per inference run
DEFAULT_TILES = 8
REFERENCE_FOLDERS = ("golden", "reference", "ref", "baseline")


def _gray_array(im: Image.Image) -> np.ndarray:
    g = im.convert("L")
    if max(g.size) > MAX_SIDE:
        g.thumbnail((MAX_SIDE, MAX_SIDE))
    return np.asarray(g, dtype=np.float32)


def tile_stats(a: np.ndarray, lap: np.ndarray, sx: np.ndarray, sy: np.ndarray, conv: np.ndarray, tiles: int):
    """Per-tile sharpness / noise / brightness / contrast / anisotropy on a ``tiles × tiles`` grid."""
    h, w = a.shape
    g = max(1, min(tiles, h, w))
    th, tw = h // g, w // g
    crop = lambda m: m[: th * g, : tw * g].reshape(g, th, g, tw)  # noqa: E731
    sharp = crop(lap).var(axis=(1, 3))
    noise = np.sqrt(np.pi / 2) / 6.0 * np.abs(crop(conv)).mean(axis=(1, 3))
    bright = crop(a).mean(axis=(1, 3))
    contrast = crop(a).std(axis=(1, 3))
    aniso = np.log((crop(sx**2).mean(axis=(1, 3)) + 1e-6) / (crop(sy**2).mean(axis=(1, 3)) + 1e-6))
    return {"sharpness": sharp, "noise": noise, "brightness": bright, "contrast": contrast, "anisotropy": aniso}


def image_analysis(im: Image.Image, tiles: int | None = None) -> tuple[dict[str, float], dict[str, np.ndarray] | None]:
    """The 17 whole-image metrics and (optionally) the per-tile grids of the five aspect values."""
    a = _gray_array(im)
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
    grids = tile_stats(a, lap, sx, sy, conv, tiles) if tiles else None
    return out, grids


def image_metrics(im: Image.Image) -> dict[str, float]:
    return image_analysis(im)[0]


def analyze_paths(
    paths: list[Path], progress=None, tiles: int | None = None
) -> tuple[np.ndarray, list[dict[str, np.ndarray] | None], list[tuple[int, int]]]:
    rows, grids, sizes = [], [], []
    for k, p in enumerate(paths):
        with Image.open(p) as im:
            sizes.append(im.size)
            m, g = image_analysis(im, tiles)
        rows.append([m[name] for name in METRICS])
        grids.append(g)
        if progress and (k % 10 == 0 or k == len(paths) - 1):
            progress((k + 1) / max(1, len(paths)))
    return np.asarray(rows, dtype=np.float64), grids, sizes


def metric_matrix(paths: list[Path], progress=None) -> np.ndarray:
    return analyze_paths(paths, progress)[0]


def deviation_grid(grids: dict[str, np.ndarray], metric: str, z: float) -> np.ndarray:
    """Tile map of where a metric's deviation concentrates: the aspect's tile values, signed so that the tiles
    pushing the metric further from the baseline come out highest (red)."""
    aspect = ASPECTS[ASPECT_OF[metric]]
    direction = float(np.sign(z) or 1.0) * aspect["metrics"][metric]
    return grids[aspect["tile"]] * direction


def aspect_direction(metric: str, z: float) -> str:
    return "high" if z * ASPECTS[ASPECT_OF[metric]]["metrics"][metric] > 0 else "low"


def advice_for(flagged: list[tuple[str, float]]) -> list[dict[str, Any]]:
    """Group (metric, z) pairs by aspect; the aspect's direction is the sign of the strongest member."""
    by_aspect: dict[str, list[tuple[str, float]]] = {}
    for m, z in flagged:
        by_aspect.setdefault(ASPECT_OF[m], []).append((m, z))
    out = []
    for aspect, items in by_aspect.items():
        strongest = max(items, key=lambda t: abs(t[1]))
        direction = aspect_direction(*strongest)
        out.append(
            {
                "aspect": aspect,
                "label": ASPECTS[aspect]["label"],
                "direction": direction,
                "metrics": [m for m, _ in sorted(items, key=lambda t: -abs(t[1]))],
                "advice": ADVICE[(aspect, direction)],
            }
        )
    return out


# -- full-reference metrics --------------------------------------------------------------------------------------


def phase_correlation(a: np.ndarray, b: np.ndarray, max_frac: float = 0.25) -> tuple[int, int]:
    """Integer displacement (dy, dx) of ``b`` relative to ``a`` (``b[y, x] ≈ a[y - dy, x - dx]``; positive = the
    test image's content sits lower / further right), from the FFT cross-power spectrum peak. |shift| >
    ``max_frac`` of the image is treated as no match (0, 0)."""
    fa = np.fft.fft2(a - a.mean())
    fb = np.fft.fft2(b - b.mean())
    cross = fa * np.conj(fb)
    cross /= np.abs(cross) + 1e-9
    corr = np.real(np.fft.ifft2(cross))
    py, px = np.unravel_index(int(np.argmax(corr)), corr.shape)
    h, w = a.shape
    dy = -int(py - h if py > h // 2 else py)
    dx = -int(px - w if px > w // 2 else px)
    if abs(dy) > max_frac * h or abs(dx) > max_frac * w:
        return 0, 0
    return dy, dx


def _overlap(a: np.ndarray, b: np.ndarray, dy: int, dx: int) -> tuple[np.ndarray, np.ndarray]:
    """Crop both to the region they share when ``b`` is displaced by (dy, dx) relative to ``a``."""
    h, w = a.shape
    ay0, ay1 = max(0, -dy), min(h, h - dy)
    ax0, ax1 = max(0, -dx), min(w, w - dx)
    return a[ay0:ay1, ax0:ax1], b[ay0 + dy : ay1 + dy, ax0 + dx : ax1 + dx]


def ssim_map(a: np.ndarray, b: np.ndarray, sigma: float = 1.5) -> tuple[np.ndarray, float]:
    """Gaussian-window SSIM map (and the mean contrast-structure term for MS-SSIM) on 0‥255 images."""
    c1, c2 = (0.01 * 255) ** 2, (0.03 * 255) ** 2
    blur = lambda m: ndimage.gaussian_filter(m, sigma, truncate=3.5)  # noqa: E731
    mu_a, mu_b = blur(a), blur(b)
    var_a = blur(a * a) - mu_a**2
    var_b = blur(b * b) - mu_b**2
    cov = blur(a * b) - mu_a * mu_b
    cs = (2 * cov + c2) / (var_a + var_b + c2)
    lum = (2 * mu_a * mu_b + c1) / (mu_a**2 + mu_b**2 + c1)
    return lum * cs, float(cs.mean())


def ms_ssim(a: np.ndarray, b: np.ndarray) -> float:
    weights = np.array([0.0448, 0.2856, 0.3001, 0.2363, 0.1333])
    levels = int(max(1, min(5, np.floor(np.log2(min(a.shape) / 16)) + 1)))
    w = weights[:levels] / weights[:levels].sum()
    vals = []
    for level in range(levels):
        smap, cs = ssim_map(a, b)
        vals.append(float(smap.mean()) if level == levels - 1 else cs)
        if level < levels - 1:
            a = ndimage.zoom(ndimage.uniform_filter(a, 2), 0.5, order=1)
            b = ndimage.zoom(ndimage.uniform_filter(b, 2), 0.5, order=1)
    return float(np.prod([max(v, 1e-6) ** wi for v, wi in zip(vals, w, strict=True)]))


def gmsd(a: np.ndarray, b: np.ndarray, c: float = 170.0) -> float:
    """Gradient magnitude similarity deviation (Xue et al. 2014): lower = closer to the reference."""
    g = lambda m: np.hypot(ndimage.prewitt(m, axis=0), ndimage.prewitt(m, axis=1)) / 3.0  # noqa: E731
    ga, gb = g(a), g(b)
    gms = (2 * ga * gb + c) / (ga**2 + gb**2 + c)
    return float(gms.std())


def full_reference(ref: Image.Image, test: Image.Image, tiles: int) -> tuple[dict[str, Any], np.ndarray]:
    """FR metrics of ``test`` against ``ref`` after integer alignment + the tile grid of (1 − SSIM)."""
    a = _gray_array(ref)
    t = test.convert("L")
    if t.size != ref.size:
        t = t.resize(ref.size, Image.BILINEAR)
    b = _gray_array(t)
    if b.shape != a.shape:
        b = np.asarray(Image.fromarray(b.astype(np.uint8)).resize((a.shape[1], a.shape[0])), dtype=np.float32)
    dy, dx = phase_correlation(a, b)
    a2, b2 = _overlap(a, b, dy, dx)
    mse = float(((a2 - b2) ** 2).mean())
    psnr = 100.0 if mse < 1e-9 else float(10 * np.log10(255.0**2 / mse))
    smap, _ = ssim_map(a2, b2)
    metrics = {
        "shift_x": dx,
        "shift_y": dy,
        "psnr": min(psnr, 100.0),
        "ssim": float(smap.mean()),
        "ms_ssim": ms_ssim(a2, b2),
        "gmsd": gmsd(a2, b2),
    }
    h, w = smap.shape
    g = max(1, min(tiles, h, w))
    th, tw = h // g, w // g
    diff = (1.0 - smap[: th * g, : tw * g]).reshape(g, th, g, tw).mean(axis=(1, 3))
    return metrics, diff


def pair_by_name(ids: list[str], reference_folder: str | None) -> tuple[str | None, dict[int, int]]:
    """Reference folder (first path component) + {test index → reference index} matched on the file name."""
    tops: dict[str, list[int]] = {}
    for n, i in enumerate(ids):
        parts = PurePosixPath(str(i).replace("\\", "/")).parts
        if len(parts) >= 2:
            tops.setdefault(parts[0], []).append(n)
    folder = reference_folder
    if folder is None:
        folder = next((f for f in REFERENCE_FOLDERS if f in tops), None)
        if folder is None:
            folder = next((f for f in tops if f.lower() in REFERENCE_FOLDERS), None)
    if folder is None or folder not in tops or len(tops) < 2:
        return None, {}
    by_name = {PurePosixPath(str(ids[n]).replace("\\", "/")).name: n for n in tops[folder]}
    pairs = {}
    for f, members in tops.items():
        if f == folder:
            continue
        for n in members:
            r = by_name.get(PurePosixPath(str(ids[n]).replace("\\", "/")).name)
            if r is not None:
                pairs[n] = r
    return folder, pairs


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
            w.writerow(["metric", "label", "aspect", "median", "scale", "low", "high", "mean", "std"])
            b = self.baseline
            for i, name in enumerate(METRICS):
                stats_row = [b.median[i], b.scale[i], b.low[i], b.high[i], b.mean[i], b.std[i]]
                w.writerow([name, LABELS[name], ASPECT_OF[name], *stats_row])
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
        paths = [Path(p) for p in ds.X]
        ids = [str(i) for i in (ds.ids or [Path(p).name for p in paths])]
        tiles = int(options.get("tiles", DEFAULT_TILES))
        maps = bool(options.get("maps", True)) and mode != "embed"
        matrix, grids, sizes = analyze_paths(
            paths, progress=lambda f: self.ctx.progress(0.7 * f), tiles=tiles if maps else None
        )
        if mode == "embed":
            rows = [
                {"id": i, "embedding": [round(float(v), 6) for v in row]} for i, row in zip(ids, matrix, strict=True)
            ]
            return PredictResult(rows, {"mode": mode, "n": len(rows), "metrics": METRICS})
        # paired full-reference metrics: a reference folder + the same file names elsewhere
        ref_folder, pairs = (None, {})
        if mode == "compare" and options.get("paired", True):
            ref_folder, pairs = pair_by_name(ids, options.get("reference_folder"))
        ref_rows = set()
        if ref_folder is not None:
            ref_rows = {n for n, i in enumerate(ids) if PurePosixPath(i.replace("\\", "/")).parts[0] == ref_folder}
            info(f"iqa: reference folder '{ref_folder}' ({len(ref_rows)} images), {len(pairs)} pairs by file name")
        keep = [n for n in range(len(ids)) if n not in ref_rows]
        b = self.baseline
        z_thr = float(options.get("z_threshold") or b.z_threshold)
        threshold = float(options.get("threshold") or b.threshold)
        z = b.zscores(matrix)
        d = b.distances(matrix)
        names: set[str] = set()
        rows = []
        for k in keep:
            i = ids[k]
            row: dict[str, Any] = {"id": i, "distance": float(d[k]), "is_anomaly": bool(d[k] > threshold)}
            flagged = [(METRICS[j], float(z[k, j])) for j in range(len(METRICS)) if abs(z[k, j]) > z_thr]
            row["out_of_range"] = [m for m, _ in flagged]
            tips = advice_for(flagged)
            row["aspects"] = [f"{t['aspect']}:{t['direction']}" for t in tips]
            row["advice"] = "；".join(f"{t['label']}：{t['advice']}" for t in tips)
            worst = int(np.argmax(np.abs(z[k])))
            row["map_metric"] = METRICS[worst]
            if maps and grids[k] is not None and len(names) < MAP_MAX:
                grid = deviation_grid(grids[k], METRICS[worst], float(z[k, worst]))
                row["map"] = "maps/" + viz.save_overlay(out / "maps", viz.overlay_name(i, names), grid, sizes[k])
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
            "distance_median": float(np.median(d[keep])) if keep else None,
            "baseline_distance_threshold": b.threshold,
        }
        extra: list[ArtifactOut] = []
        if mode == "compare":
            table = self._compare(matrix[keep], options)
            summary.update(table["summary"])
            summary["per_metric"] = table["per_metric"]
            summary["advice"] = table["advice"]
            if pairs:
                self._paired(rows, keep, ids, paths, pairs, tiles, maps, names, out, options, summary, extra)
            (out / "comparison.json").write_text(jsonsafe.dumps(table, indent=2), encoding="utf-8")
            with (out / "comparison.csv").open("w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=list(table["per_metric"][0].keys()))
                w.writeheader()
                w.writerows(table["per_metric"])
            extra.append(
                ArtifactOut(name="tool_matching_report", kind="report", path="output/comparison.csv", framework="numpy")
            )
        return PredictResult(rows, summary, extra)

    def _paired(self, rows, keep, ids, paths, pairs, tiles, maps, names, out, options, summary, extra) -> None:
        """Full-reference metrics for every (test, reference) pair; writes output/paired.csv and SSIM overlays."""
        ssim_warn = float(options.get("ssim_warn", 0.9))
        ssim_fail = float(options.get("ssim_fail", 0.7))
        row_of = {k: r for k, r in zip(keep, rows, strict=True)}
        paired_rows = []
        for n, (k, r) in enumerate(pairs.items()):
            row = row_of.get(k)
            if row is None:
                continue
            with Image.open(paths[r]) as ref, Image.open(paths[k]) as test:
                fr, diff = full_reference(ref, test, tiles)
            row["reference"] = ids[r]
            row.update(fr)
            if maps and len(names) < MAP_MAX:
                row["map"] = "maps/" + viz.save_overlay(
                    out / "maps", viz.overlay_name(f"paired/{ids[k]}", names), diff, Image.open(paths[k]).size
                )
                row["map_metric"] = "ssim"
            paired_rows.append({"id": ids[k], "reference": ids[r], **fr})
            if n % 10 == 0:
                self.ctx.progress(0.7 + 0.25 * (n + 1) / len(pairs))
        if not paired_rows:
            return
        with (out / "paired.csv").open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(paired_rows[0].keys()))
            w.writeheader()
            w.writerows(paired_rows)
        extra.append(ArtifactOut(name="paired_report", kind="report", path="output/paired.csv", framework="numpy"))
        mean = lambda key: float(np.mean([p[key] for p in paired_rows]))  # noqa: E731
        s_mean = mean("ssim")
        verdict = "pass" if s_mean >= ssim_warn else ("drift" if s_mean >= ssim_fail else "fail")
        summary["paired"] = {
            "n": len(paired_rows),
            "psnr_mean": mean("psnr"),
            "ssim_mean": s_mean,
            "ms_ssim_mean": mean("ms_ssim"),
            "gmsd_mean": mean("gmsd"),
            "ssim_min": float(min(p["ssim"] for p in paired_rows)),
            "verdict": verdict,
        }
        rank = {"pass": 0, "drift": 1, "fail": 2}
        if rank[verdict] > rank.get(summary.get("verdict", "pass"), 0):
            summary["verdict"] = verdict

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
                    "aspect": ASPECT_OF[name],
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
        advice = advice_for([(m["metric"], m["effect"]) for m in per_metric if m["verdict"] != "match"])
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
            "advice": advice,
        }
