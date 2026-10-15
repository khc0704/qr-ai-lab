"""Sequence / spectrum ops on float32 arrays of shape (N, T, C)."""

from __future__ import annotations

import numpy as np
from scipy import ndimage, signal

from qrlab_preprocess.base import Context, Op, Param, register

SEQ = ("SEQUENCE", "SPECTRUM")


def _arr(x) -> np.ndarray:
    a = np.asarray(x, dtype=np.float32)
    if a.ndim == 2:
        a = a[:, :, None]
    if a.ndim != 3:
        raise ValueError(f"序列資料需要 (N, T) 或 (N, T, C)，得到 {a.shape}")
    return a


def _odd_window(w: int, T: int) -> int:
    w = max(3, min(int(w), T if T % 2 else T - 1))
    return w if w % 2 else w - 1


@register
class Resample(Op):
    id = "sequence.resample"
    label = "重取樣長度"
    description = "線性內插到固定點數（長度不一致的光譜 / 視窗先統一）。"
    data_types = SEQ
    params = (Param("length", "點數", "int", default=256, min=4, max=100000),)

    def apply(self, x, ctx: Context) -> np.ndarray:
        a = _arr(x)
        N, T, C = a.shape
        L = self.p["length"]
        if T == L:
            return a
        src, dst = np.linspace(0, 1, T), np.linspace(0, 1, L)
        out = np.empty((N, L, C), np.float32)
        for c in range(C):
            out[:, :, c] = np.stack([np.interp(dst, src, a[n, :, c]) for n in range(N)])
        return out


@register
class CropRange(Op):
    id = "sequence.crop"
    label = "裁切範圍"
    description = "只保留第 start 到 end 個點（例如去掉光譜兩端的雜訊區）。"
    data_types = SEQ
    params = (
        Param("start", "起點（含）", "int", default=0, min=0),
        Param("end", "終點（不含，0 = 到底）", "int", default=0, min=0),
    )

    def apply(self, x, ctx: Context) -> np.ndarray:
        a = _arr(x)
        end = self.p["end"] or a.shape[1]
        if self.p["start"] >= end:
            raise ValueError("start 必須小於 end")
        return a[:, self.p["start"] : end, :]


@register
class FillNaN(Op):
    id = "sequence.fill_nan"
    label = "補缺值（線性內插）"
    data_types = SEQ

    def apply(self, x, ctx: Context) -> np.ndarray:
        a = _arr(x).copy()
        N, T, C = a.shape
        idx = np.arange(T)
        for n in range(N):
            for c in range(C):
                v = a[n, :, c]
                bad = ~np.isfinite(v)
                if bad.any() and (~bad).any():
                    v[bad] = np.interp(idx[bad], idx[~bad], v[~bad])
                elif bad.all():
                    v[:] = 0
        return a


@register
class SavgolSmooth(Op):
    id = "sequence.savgol"
    label = "Savitzky–Golay 平滑"
    data_types = SEQ
    params = (
        Param("window", "視窗（奇數）", "int", default=11, min=3, max=999),
        Param("polyorder", "多項式階數", "int", default=2, min=1, max=6),
    )

    def apply(self, x, ctx: Context) -> np.ndarray:
        a = _arr(x)
        w = _odd_window(self.p["window"], a.shape[1])
        return signal.savgol_filter(a, w, min(self.p["polyorder"], w - 1), axis=1).astype(np.float32)


@register
class MovingAverage(Op):
    id = "sequence.moving_average"
    label = "移動平均"
    data_types = SEQ
    params = (Param("window", "視窗", "int", default=5, min=2, max=999),)

    def apply(self, x, ctx: Context) -> np.ndarray:
        a = _arr(x)
        return ndimage.uniform_filter1d(a, size=min(self.p["window"], a.shape[1]), axis=1, mode="nearest").astype(
            np.float32
        )


@register
class Derivative(Op):
    id = "sequence.derivative"
    label = "微分（Savitzky–Golay）"
    description = "一階 / 二階導數，去除基線偏移並強化峰的位置。"
    data_types = SEQ
    params = (
        Param("order", "階數", "choice", default=1, choices=(1, 2)),
        Param("window", "視窗（奇數）", "int", default=11, min=5, max=999),
        Param("polyorder", "多項式階數", "int", default=3, min=2, max=6),
    )

    def apply(self, x, ctx: Context) -> np.ndarray:
        a = _arr(x)
        w = _odd_window(self.p["window"], a.shape[1])
        order = int(self.p["order"])
        return signal.savgol_filter(a, w, max(order, min(self.p["polyorder"], w - 1)), deriv=order, axis=1).astype(
            np.float32
        )


@register
class BaselinePoly(Op):
    id = "sequence.baseline_poly"
    label = "基線校正（多項式）"
    description = "每條曲線擬合低階多項式當基線並減去。"
    data_types = SEQ
    params = (Param("degree", "階數", "int", default=2, min=0, max=6),)

    def apply(self, x, ctx: Context) -> np.ndarray:
        a = _arr(x).copy()
        t = np.linspace(-1, 1, a.shape[1])
        for c in range(a.shape[2]):
            coef = np.polynomial.polynomial.polyfit(t, a[:, :, c].T, self.p["degree"])
            a[:, :, c] -= np.polynomial.polynomial.polyval(t, coef).astype(np.float32)  # (N, T)
        return a


@register
class BaselineRollingMin(Op):
    id = "sequence.baseline_rolling_min"
    label = "基線校正（滾動最小值）"
    description = "以滾動最小值再平滑當基線，適合有寬背景的光譜（拉曼螢光背景等）。"
    data_types = SEQ
    params = (Param("window", "視窗", "int", default=51, min=5, max=9999),)

    def apply(self, x, ctx: Context) -> np.ndarray:
        a = _arr(x)
        w = min(self.p["window"], a.shape[1])
        base = ndimage.minimum_filter1d(a, size=w, axis=1, mode="nearest")
        base = ndimage.uniform_filter1d(base, size=w, axis=1, mode="nearest")
        return (a - base).astype(np.float32)


@register
class Detrend(Op):
    id = "sequence.detrend"
    label = "去趨勢（線性）"
    data_types = SEQ

    def apply(self, x, ctx: Context) -> np.ndarray:
        return signal.detrend(_arr(x), axis=1, type="linear").astype(np.float32)


@register
class SNV(Op):
    id = "sequence.snv"
    label = "SNV（每條曲線標準化）"
    description = "每條曲線各自減平均、除標準差；消除散射 / 強度差異。"
    data_types = SEQ

    def apply(self, x, ctx: Context) -> np.ndarray:
        a = _arr(x)
        m = a.mean(axis=1, keepdims=True)
        s = a.std(axis=1, keepdims=True) + 1e-8
        return ((a - m) / s).astype(np.float32)


@register
class MinMaxPerSample(Op):
    id = "sequence.minmax_sample"
    label = "每條曲線歸一化 0–1"
    data_types = SEQ

    def apply(self, x, ctx: Context) -> np.ndarray:
        a = _arr(x)
        lo = a.min(axis=1, keepdims=True)
        hi = a.max(axis=1, keepdims=True)
        return ((a - lo) / np.maximum(hi - lo, 1e-8)).astype(np.float32)


@register
class MSC(Op):
    id = "sequence.msc"
    label = "MSC（乘法散射校正）"
    description = "以訓練集平均曲線為參考，每條曲線做線性回歸校正；參考曲線在訓練時學到。"
    data_types = SEQ
    fitted = True

    def fit(self, x, ctx: Context) -> None:
        self.state = {"reference": _arr(x).mean(axis=0)}

    def apply(self, x, ctx: Context) -> np.ndarray:
        a = _arr(x)
        ref = np.asarray(self.state["reference"], np.float32)
        if ref.shape != a.shape[1:]:
            raise ValueError(f"MSC 參考曲線長度 {ref.shape} 與輸入 {a.shape[1:]} 不一致（先用重取樣）")
        out = np.empty_like(a)
        for c in range(a.shape[2]):
            r = ref[:, c]
            A = np.stack([np.ones_like(r), r], axis=1)
            coef, *_ = np.linalg.lstsq(A, a[:, :, c].T, rcond=None)  # (2, N)
            out[:, :, c] = (
                (a[:, :, c] - coef[0][:, None]) / np.where(np.abs(coef[1]) < 1e-8, 1.0, coef[1])[:, None]
            ).astype(np.float32)
        return out


@register
class StandardizeChannels(Op):
    id = "sequence.standardize"
    label = "標準化（整體 z-score）"
    description = "每個通道以訓練集的平均 / 標準差標準化。"
    data_types = SEQ
    fitted = True

    def fit(self, x, ctx: Context) -> None:
        a = _arr(x)
        self.state = {"mean": a.mean(axis=(0, 1)), "std": a.std(axis=(0, 1)) + 1e-8}

    def apply(self, x, ctx: Context) -> np.ndarray:
        a = _arr(x)
        return ((a - np.asarray(self.state["mean"], np.float32)) / np.asarray(self.state["std"], np.float32)).astype(
            np.float32
        )


@register
class ClipValues(Op):
    id = "sequence.clip"
    label = "截斷數值範圍"
    data_types = SEQ
    params = (Param("min", "最小值", "float", default=-1e9), Param("max", "最大值", "float", default=1e9))

    def apply(self, x, ctx: Context) -> np.ndarray:
        return np.clip(_arr(x), self.p["min"], self.p["max"]).astype(np.float32)
