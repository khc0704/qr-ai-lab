"""Image quality exploration across machines / conditions: which IQA metrics drift between groups, how similar
the groups are in embedding space, which images stand out."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np

from trainer.log import warn
from trainer.models.iqa import LABELS, METRICS, image_metrics

MAX_IMAGES = 2000
MAX_POINTS = 600


def _groups(root: Path, paths: list[Path]) -> list[str]:
    out = []
    for p in paths:
        rel = p.relative_to(root)
        out.append(rel.parts[0] if len(rel.parts) > 1 else "all")
    return out


def _zscore(M: np.ndarray) -> np.ndarray:
    mu = np.nanmedian(M, axis=0)
    sd = np.nanstd(M, axis=0) + 1e-9
    return (M - mu) / sd


def _pca2(E: np.ndarray) -> np.ndarray:
    X = E - E.mean(axis=0)
    if X.shape[0] < 2 or X.shape[1] < 2:
        return np.zeros((X.shape[0], 2))
    U, S, _ = np.linalg.svd(X, full_matrices=False)
    coords = U[:, :2] * S[:2]
    if coords.shape[1] < 2:
        coords = np.column_stack([coords, np.zeros(len(coords))])
    return coords


def quality_report(
    root: Path,
    *,
    embedding: str = "metrics",
    backbone: str = "dinov2-small",
    ctx=None,
    progress: Callable[[float], None] | None = None,
) -> dict[str, Any]:
    from trainer.data.image import all_images

    tick = progress or (lambda f: None)
    paths = all_images(root)
    if not paths:
        raise ValueError("找不到影像檔")
    sampled = len(paths) > MAX_IMAGES
    if sampled:
        rng = np.random.default_rng(0)
        paths = sorted(rng.choice(paths, MAX_IMAGES, replace=False).tolist())
    groups = _groups(root, paths)
    labels = sorted(set(groups))
    rows = []
    for k, p in enumerate(paths):
        from PIL import Image

        with Image.open(p) as im:
            m = image_metrics(im)
        rows.append([m[name] for name in METRICS])
        if k % 10 == 0:
            tick(0.6 * (k + 1) / len(paths))
    M = np.asarray(rows, dtype=np.float64)
    g = np.asarray(groups)
    tick(0.6)

    # --- per group statistics + drift ----------------------------------------------------------------
    per_group: dict[str, dict[str, Any]] = {}
    for lab in labels:
        sel = g == lab
        q1, med, q3 = np.percentile(M[sel], [25, 50, 75], axis=0)
        per_group[lab] = {
            "images": int(sel.sum()),
            "median": {n: float(v) for n, v in zip(METRICS, med, strict=True)},
            "iqr": {n: float(v) for n, v in zip(METRICS, q3 - q1, strict=True)},
        }
    drift: list[dict[str, Any]] = []
    overall_sd = M.std(axis=0) + 1e-9
    for j, name in enumerate(METRICS):
        meds = np.array([per_group[lab]["median"][name] for lab in labels])
        iqrs = np.array([per_group[lab]["iqr"][name] for lab in labels])
        spread = float(meds.max() - meds.min()) if len(labels) > 1 else 0.0
        within = float(np.median(iqrs)) + 1e-9
        pval = None
        if len(labels) > 1 and all((g == lab).sum() >= 3 for lab in labels):
            try:
                from scipy.stats import kruskal

                pval = float(kruskal(*[M[g == lab, j] for lab in labels]).pvalue)
            except Exception:
                pval = None
        drift.append(
            {
                "metric": name,
                "label": LABELS.get(name, name),
                "spread": spread,
                "spread_sd": round(spread / float(overall_sd[j]), 3),
                "drift_ratio": round(spread / within, 3),
                "p_value": pval,
                "group_medians": {lab: per_group[lab]["median"][name] for lab in labels},
            }
        )
    drift.sort(key=lambda d: -d["drift_ratio"])
    for i, d in enumerate(drift, 1):
        d["rank"] = i
    tick(0.7)

    # --- embeddings -----------------------------------------------------------------------------------
    emb_kind = "metrics"
    E = _zscore(M)
    if embedding == "dino":
        try:
            from trainer.models.vision import _Dino

            if ctx is None:
                raise RuntimeError("no context")
            E = _Dino(ctx, backbone).embed(paths, progress=lambda f: tick(0.7 + 0.15 * f))
            emb_kind = f"dino:{backbone}"
        except Exception as e:
            warn(f"dino embedding unavailable ({type(e).__name__}: {e}); using the IQA metric vector instead")
    coords = _pca2(E)
    En = E / (np.linalg.norm(E, axis=1, keepdims=True) + 1e-9)
    centroids = {lab: En[g == lab].mean(axis=0) for lab in labels}
    sim = [
        [
            float(
                np.dot(centroids[a], centroids[b])
                / (np.linalg.norm(centroids[a]) * np.linalg.norm(centroids[b]) + 1e-9)
            )
            for b in labels
        ]
        for a in labels
    ]
    silhouette = None
    if len(labels) > 1 and len(paths) > len(labels):
        try:
            from sklearn.metrics import silhouette_score

            silhouette = float(silhouette_score(En, g, metric="cosine"))
        except Exception:
            silhouette = None
    # outliers: distance to the own group's centroid, robust z within the group
    dist = np.array(
        [
            1 - float(np.dot(En[i], centroids[g[i]]) / (np.linalg.norm(centroids[g[i]]) + 1e-9))
            for i in range(len(paths))
        ]
    )
    oscore = np.zeros(len(paths))
    for lab in labels:
        sel = g == lab
        med = np.median(dist[sel])
        mad = np.median(np.abs(dist[sel] - med)) + 1e-9
        oscore[sel] = 0.6745 * (dist[sel] - med) / mad
    order = np.argsort(-oscore)
    outliers = [
        {
            "id": str(paths[i].relative_to(root)),
            "group": groups[i],
            "score": round(float(oscore[i]), 2),
            "metrics": {n: round(float(M[i, j]), 4) for j, n in enumerate(METRICS)},
        }
        for i in order[:10]
        if oscore[i] > 3.5
    ]
    tick(0.9)

    # --- recommendations ------------------------------------------------------------------------------
    recs: list[dict[str, str]] = []
    top = [d for d in drift[:3] if d["drift_ratio"] > 1.0]
    if len(labels) == 1:
        recs.append(
            {
                "level": "info",
                "text": "只有一個群組（zip 內沒有子資料夾）：把不同機台 / 條件放在不同資料夾再上傳，才能比較飄移。",
            }
        )
    elif top:
        names = "、".join(f"{d['label']}（群組中位數差 = {d['drift_ratio']:.1f} × 群內 IQR）" for d in top)
        recs.append(
            {"level": "warn", "text": f"群組之間最會飄的指標：{names}；建議列為機台比對（compare 模式）的監控重點。"}
        )
    else:
        recs.append(
            {"level": "info", "text": "各群組的 IQA 指標中位數差異都在群內變異範圍內，影像品質面向沒有明顯飄移。"}
        )
    hints = {
        "brightness_mean": "亮度 → 檢查照明 / 曝光設定",
        "brightness_p99": "亮部 → 檢查曝光或增益",
        "sharpness_laplacian": "清晰度 → 檢查對焦、像散或樣品高度",
        "sharpness_tenengrad": "清晰度 → 檢查對焦",
        "noise_sigma": "雜訊 → 檢查增益、掃描速度或積分時間",
        "snr": "訊噪比 → 檢查增益與積分時間",
        "contrast_rms": "對比 → 檢查偵測器 / 亮度對比設定",
        "hf_energy_ratio": "高頻能量 → 對焦或倍率差異",
        "anisotropy_gradient": "方向性 → 掃描方向 / 像散",
        "anisotropy_fft": "方向性 → 掃描方向 / 像散",
    }
    for d in top:
        if d["metric"] in hints:
            recs.append({"level": "info", "text": hints[d["metric"]]})
    if silhouette is not None:
        if silhouette > 0.5:
            recs.append(
                {
                    "level": "warn",
                    "text": f"embedding（{emb_kind}）在群組之間分得很開（silhouette = {silhouette:.2f}）："
                    "這些機台 / 條件拍出來的影像風格明顯不同，模型需要涵蓋各群組的資料。",
                }
            )
        elif silhouette > 0.25:
            recs.append(
                {"level": "info", "text": f"embedding 部分可分（silhouette = {silhouette:.2f}）：群組有差異但有重疊。"}
            )
        else:
            recs.append(
                {
                    "level": "info",
                    "text": f"embedding 幾乎分不開（silhouette = {silhouette:.2f}）：各群組影像在品質面向上相似。",
                }
            )
    if len(labels) > 1:
        worst = min(
            ((a, b, sim[i][j]) for i, a in enumerate(labels) for j, b in enumerate(labels) if j > i),
            key=lambda t: t[2],
            default=None,
        )
        if worst:
            recs.append(
                {
                    "level": "info",
                    "text": f"最不相似的兩個群組：{worst[0]} 與 {worst[1]}（centroid cosine = {worst[2]:.3f}）。",
                }
            )
    if outliers:
        recs.append(
            {
                "level": "info",
                "text": f"偏離自己群組最多的影像：{', '.join(o['id'] for o in outliers[:5])}；"
                "先確認是否為拍攝失誤或真實異常。",
            }
        )
    if emb_kind == "metrics" and embedding == "dino":
        recs.append(
            {"level": "info", "text": "DINOv2 權重或 GPU 不可用，這次的 embedding 是 17 個 IQA 指標的 z-score 向量。"}
        )
    tick(1.0)
    stride = max(1, len(paths) // MAX_POINTS)
    return {
        "images_total": len(paths),
        "sampled": sampled,
        "groups": [{"name": lab, **per_group[lab]} for lab in labels],
        "metrics": [{"name": n, "label": LABELS.get(n, n)} for n in METRICS],
        "drift": drift,
        "embedding": emb_kind,
        "silhouette": silhouette,
        "similarity": {"labels": labels, "matrix": [[round(v, 4) for v in row] for row in sim]},
        "points": [
            {
                "id": str(paths[i].relative_to(root)),
                "group": groups[i],
                "x": round(float(coords[i, 0]), 4),
                "y": round(float(coords[i, 1]), 4),
                "outlier": round(float(oscore[i]), 2),
            }
            for i in range(0, len(paths), stride)
        ],
        "outliers": outliers,
        "recommendations": recs,
    }
