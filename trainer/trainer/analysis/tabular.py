"""Tabular data exploration: what correlates, what is collinear, what explains the target, what to do next."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import numpy as np
import pandas as pd

from trainer.jsonsafe import finite
from trainer.log import info

MAX_ROWS = 50_000
MAX_CORR_COLUMNS = 40
MAX_CATEGORIES = 50
MAX_PERM_COLUMNS = 50  # permutation importance: top columns by mutual information
MAX_PERM_ROWS = 2000  # permutation importance: holdout rows (5 repeats × columns × rows predictions)


def _num(v: Any) -> float | None:
    """A statistic as a float, or ``None`` when it does not exist (NaN / inf: one value has no std, a constant
    target has no R², …). The report never carries NaN."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if np.isfinite(f) else None


def _dtype(s: pd.Series) -> str:
    if pd.api.types.is_bool_dtype(s):
        return "categorical"
    if pd.api.types.is_numeric_dtype(s):
        return "numeric"
    if pd.api.types.is_datetime64_any_dtype(s):
        return "datetime"
    return "categorical" if s.nunique(dropna=True) <= MAX_CATEGORIES else "text"


def _column_summary(df: pd.DataFrame) -> list[dict[str, Any]]:
    out = []
    n = max(1, len(df))
    for c in df.columns:
        s = df[c]
        entry: dict[str, Any] = {
            "name": str(c),
            "dtype": _dtype(s),
            "missing_ratio": round(float(s.isna().mean()), 4),
            "unique": int(s.nunique(dropna=True)),
        }
        if entry["dtype"] == "numeric" and s.notna().any():
            x = s.astype(float)
            q1, q3 = x.quantile([0.25, 0.75])
            std = _num(x.std())  # NaN for a single value (ddof = 1)
            z = ((x - x.mean()) / (std or 1.0)).abs()
            entry.update(
                {
                    "mean": _num(x.mean()),
                    "std": std if std is not None else 0.0,
                    "min": _num(x.min()),
                    "max": _num(x.max()),
                    "skew": (_num(x.skew()) if len(x.dropna()) > 2 else None) or 0.0,
                    "outlier_ratio": round(float((z > 5).mean()), 4),
                    "iqr": _num(q3 - q1),
                }
            )
        elif entry["dtype"] in ("categorical", "text"):
            top = s.astype("string").value_counts(dropna=True).head(5)
            entry["top_values"] = [{"value": str(k), "count": int(v)} for k, v in top.items()]
            entry["top_ratio"] = round(float(top.iloc[0] / n), 4) if len(top) else 0.0
        out.append(entry)
    return out


def _vif(X: np.ndarray) -> list[float]:
    """Variance inflation factor per column (standardized, NaN-free)."""
    n, p = X.shape
    if p < 2 or n <= p + 1:
        return [float("nan")] * p
    Xs = (X - X.mean(axis=0)) / (X.std(axis=0) + 1e-12)
    out = []
    for j in range(p):
        y = Xs[:, j]
        A = np.delete(Xs, j, axis=1)
        A = np.column_stack([A, np.ones(n)])
        coef, *_ = np.linalg.lstsq(A, y, rcond=None)
        resid = y - A @ coef
        ss_res = float((resid**2).sum())
        ss_tot = float(((y - y.mean()) ** 2).sum()) + 1e-12
        r2 = max(0.0, min(1.0, 1 - ss_res / ss_tot))
        out.append(float(1.0 / max(1e-6, 1 - r2)) if r2 < 0.999999 else float("inf"))
    return out


def _encode(df: pd.DataFrame, numeric: list[str], categorical: list[str]) -> tuple[np.ndarray, list[str], list[bool]]:
    cols: list[np.ndarray] = []
    names: list[str] = []
    discrete: list[bool] = []
    for c in numeric:
        x = df[c].astype(float)
        cols.append(x.fillna(x.median() if x.notna().any() else 0.0).to_numpy())
        names.append(c)
        discrete.append(False)
    for c in categorical:
        codes = df[c].astype("string").fillna("<NA>").astype("category").cat.codes.to_numpy().astype(float)
        cols.append(codes)
        names.append(c)
        discrete.append(True)
    X = np.column_stack(cols) if cols else np.zeros((len(df), 0))
    return X, names, discrete


def _eta_squared(x: np.ndarray, groups: np.ndarray) -> float:
    """Share of a numeric feature's variance explained by the class label (ANOVA η²)."""
    total = float(((x - x.mean()) ** 2).sum()) + 1e-12
    between = 0.0
    for g in np.unique(groups):
        sel = groups == g
        between += sel.sum() * float((x[sel].mean() - x.mean()) ** 2)
    return float(max(0.0, min(1.0, between / total)))


def profile(
    df: pd.DataFrame,
    *,
    target: str | None = None,
    task: str | None = None,
    id_columns: list[str] | None = None,
    n_jobs: int = 1,
    progress: Callable[[float], None] | None = None,
) -> dict[str, Any]:
    tick = progress or (lambda f: None)
    df = df.copy()
    for c in id_columns or []:
        if c in df.columns:
            df = df.drop(columns=[c])
    if len(df) > MAX_ROWS:
        df = df.sample(MAX_ROWS, random_state=0)
    report: dict[str, Any] = {"rows": len(df), "columns_total": int(df.shape[1]), "sampled": len(df) >= MAX_ROWS}
    columns = _column_summary(df)
    report["columns"] = columns
    by_name = {c["name"]: c for c in columns}
    if target and target not in df.columns:
        raise ValueError(f"找不到目標欄位 {target}")
    numeric = [c for c in df.columns if by_name[str(c)]["dtype"] == "numeric" and c != target]
    categorical = [c for c in df.columns if by_name[str(c)]["dtype"] == "categorical" and c != target]
    recommendations: list[dict[str, str]] = []
    tick(0.15)

    # --- correlation + collinearity -------------------------------------------------------------
    num_df = df[numeric].astype(float)
    keep = [c for c in numeric if num_df[c].std(skipna=True) > 0]
    constant = [c for c in numeric if c not in keep]
    corr_cols = sorted(keep, key=lambda c: -float(num_df[c].std()))[:MAX_CORR_COLUMNS]
    corr = num_df[corr_cols].corr(method="pearson") if len(corr_cols) >= 2 else pd.DataFrame()
    pairs: list[dict[str, Any]] = []
    if not corr.empty:
        vals = corr.to_numpy()
        for i in range(len(corr_cols)):
            for j in range(i + 1, len(corr_cols)):
                r = float(vals[i, j])
                if np.isfinite(r) and abs(r) >= 0.7:
                    pairs.append({"a": corr_cols[i], "b": corr_cols[j], "r": round(r, 4)})
        pairs.sort(key=lambda d: -abs(d["r"]))
    report["correlation"] = {
        "columns": corr_cols,
        "matrix": [[round(float(v), 3) if np.isfinite(v) else None for v in row] for row in corr.to_numpy()]
        if not corr.empty
        else [],
        "high_pairs": pairs[:50],
    }
    vif_rows: list[dict[str, Any]] = []
    if len(corr_cols) >= 2:
        X = num_df[corr_cols].fillna(num_df[corr_cols].median()).to_numpy()
        for name, v in zip(corr_cols, _vif(X), strict=True):
            vif_rows.append({"name": name, "vif": None if not np.isfinite(v) else round(float(v), 2)})
        vif_rows.sort(key=lambda d: -(d["vif"] if d["vif"] is not None else 1e9))
    report["collinearity"] = {"vif": vif_rows}
    tick(0.4)

    # --- relevance to the target -----------------------------------------------------------------
    relevance: dict[str, Any] = {"target": target, "task": None, "features": [], "model": None, "leakage": []}
    if target:
        y_raw = df[target]
        y_num = pd.api.types.is_numeric_dtype(y_raw) and not pd.api.types.is_bool_dtype(y_raw)
        task = task or ("regression" if (y_num and y_raw.nunique(dropna=True) > 20) else "classification")
        mask = y_raw.notna().to_numpy()
        X, names, discrete = _encode(df[mask], [c for c in keep], categorical)
        y = y_raw[mask]
        feats: dict[str, dict[str, Any]] = {
            n: {"name": n, "kind": "categorical" if d else "numeric"} for n, d in zip(names, discrete, strict=True)
        }
        if X.shape[1] and len(y) >= 20:
            from sklearn.feature_selection import mutual_info_classif, mutual_info_regression

            if task == "regression":
                yv = y.astype(float).to_numpy()
                mi = mutual_info_regression(X, yv, discrete_features=discrete, random_state=0)
                for k, n in enumerate(names):
                    if not discrete[k]:
                        r = float(np.corrcoef(X[:, k], yv)[0, 1]) if X[:, k].std() > 0 else 0.0
                        feats[n]["corr_target"] = round(r if np.isfinite(r) else 0.0, 4)
                    else:
                        feats[n]["corr_target"] = round(_eta_squared(yv, X[:, k]) ** 0.5, 4)
            else:
                yv = y.astype("string").astype("category").cat.codes.to_numpy()
                mi = mutual_info_classif(X, yv, discrete_features=discrete, random_state=0)
                for k, n in enumerate(names):
                    feats[n]["corr_target"] = round(_eta_squared(X[:, k], yv) ** 0.5, 4) if not discrete[k] else None
            mi_max = float(mi.max()) if len(mi) and mi.max() > 0 else 1.0
            for k, n in enumerate(names):
                feats[n]["mutual_info"] = round(float(mi[k]), 4)
                feats[n]["mutual_info_norm"] = round(float(mi[k] / mi_max), 4)
            tick(0.55)
            # a quick model: holdout score + permutation importance (what the target actually depends on)
            try:
                from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
                from sklearn.inspection import permutation_importance
                from sklearn.model_selection import train_test_split

                strat = yv if task == "classification" and len(np.unique(yv)) > 1 and len(yv) >= 40 else None
                # the quick model sees the top columns by mutual information; the rest are reported as skipped
                cols = (
                    sorted(np.argsort(-mi)[:MAX_PERM_COLUMNS].tolist())
                    if X.shape[1] > MAX_PERM_COLUMNS
                    else list(range(X.shape[1]))
                )
                Xtr, Xte, ytr, yte = train_test_split(X[:, cols], yv, test_size=0.3, random_state=0, stratify=strat)
                est = (
                    RandomForestRegressor(n_estimators=200, random_state=0, n_jobs=max(1, n_jobs))
                    if task == "regression"
                    else RandomForestClassifier(n_estimators=200, random_state=0, n_jobs=max(1, n_jobs))
                )
                est.fit(Xtr, ytr)
                score = _num(est.score(Xte, yte))  # None: a constant holdout target has no R²
                Xpe, ype = Xte, yte
                if len(Xte) > MAX_PERM_ROWS:
                    sel = np.sort(np.random.default_rng(0).choice(len(Xte), MAX_PERM_ROWS, replace=False))
                    Xpe, ype = Xte[sel], yte[sel]
                capped = []
                if len(cols) < X.shape[1]:
                    capped.append(f"columns {X.shape[1]} → top {len(cols)} by mutual information")
                if len(Xpe) < len(Xte):
                    capped.append(f"holdout rows {len(Xte)} → {len(Xpe)}")
                if capped:
                    info("tabular profile: permutation importance capped (" + "; ".join(capped) + ")")
                perm = permutation_importance(est, Xpe, ype, n_repeats=5, random_state=0, n_jobs=max(1, n_jobs))
                imp = np.zeros(X.shape[1])
                imp[cols] = perm.importances_mean
                imp_sum = float(np.clip(imp, 0, None).sum()) or 1.0
                used = set(cols)
                for k, n in enumerate(names):
                    feats[n]["permutation_importance"] = round(float(imp[k]), 4)
                    feats[n]["importance_share"] = round(float(max(0.0, imp[k]) / imp_sum), 4)
                    if k not in used:
                        feats[n]["permutation_skipped"] = True
                relevance["model"] = {
                    "estimator": type(est).__name__,
                    "metric": "r2" if task == "regression" else "accuracy",
                    "holdout_score": round(score, 4) if score is not None else None,
                    "train_rows": len(ytr),
                    "test_rows": len(yte),
                    "columns_used": len(cols),
                    "permutation_rows": len(Xpe),
                }
            except Exception as e:  # the profile is still useful without the model
                relevance["model"] = {"error": f"{type(e).__name__}: {e}"[:300]}
        rows = list(feats.values())
        for f in rows:
            f["score"] = round(
                0.5 * float(f.get("mutual_info_norm") or 0.0)
                + 0.3 * float(f.get("importance_share") or 0.0)
                + 0.2 * abs(float(f.get("corr_target") or 0.0)),
                4,
            )
        rows.sort(key=lambda f: -f["score"])
        for i, f in enumerate(rows, 1):
            f["rank"] = i
        relevance["task"] = task
        relevance["features"] = rows
        relevance["leakage"] = [
            f["name"]
            for f in rows
            if abs(float(f.get("corr_target") or 0.0)) > 0.98 or float(f.get("importance_share") or 0.0) > 0.9
        ]
    report["relevance"] = relevance
    tick(0.85)

    # --- recommendations ---------------------------------------------------------------------------
    missing = [c["name"] for c in columns if c["missing_ratio"] > 0.3 and c["name"] != target]
    some_missing = any(c["missing_ratio"] > 0 for c in columns if c["name"] != target)
    if missing:
        recommendations.append(
            {
                "level": "warn",
                "text": f"缺值超過 30% 的欄位：{', '.join(missing[:8])}；"
                "建議移除或先確認缺值原因，再用 tabular.impute 補值。",
            }
        )
    elif some_missing:
        recommendations.append(
            {"level": "info", "text": "有欄位含缺值：建立任務時加入 tabular.impute（中位數 / 眾數）即可。"}
        )
    if constant:
        recommendations.append(
            {"level": "info", "text": f"常數欄位（沒有變化，對模型沒有幫助）：{', '.join(constant[:8])}。"}
        )
    strong = [p for p in pairs if abs(p["r"]) >= 0.9]
    if strong:
        txt = "、".join(f"{p['a']} ↔ {p['b']}（r={p['r']:+.2f}）" for p in strong[:5])
        recommendations.append(
            {"level": "warn", "text": f"高度共線的欄位對：{txt}；每對保留一個即可，線性模型尤其需要。"}
        )
    high_vif = [v["name"] for v in vif_rows if v["vif"] is not None and v["vif"] > 10]
    if high_vif:
        recommendations.append(
            {"level": "info", "text": f"VIF > 10（可由其他欄位線性組合出來）：{', '.join(high_vif[:8])}。"}
        )
    heavy = [c["name"] for c in columns if c.get("outlier_ratio", 0) > 0.01]
    if heavy:
        recommendations.append(
            {
                "level": "info",
                "text": f"離群值比例 > 1% 的欄位：{', '.join(heavy[:8])}；"
                "可加 tabular.clip_outliers，或改用樹模型（XGBoost / 隨機森林）。",
            }
        )
    if target and relevance["features"]:
        top = [f["name"] for f in relevance["features"][:5]]
        recommendations.append(
            {"level": "info", "text": f"對目標最有解釋力的欄位：{', '.join(top)}（綜合互資訊、相關性與置換重要度）。"}
        )
        weak = [f["name"] for f in relevance["features"] if f["score"] < 0.05]
        if weak:
            recommendations.append({"level": "info", "text": f"幾乎沒有解釋力、可考慮移除：{', '.join(weak[:10])}。"})
        if relevance["leakage"]:
            recommendations.append(
                {
                    "level": "warn",
                    "text": f"疑似資料洩漏（和目標幾乎一對一）：{', '.join(relevance['leakage'])}；"
                    "確認這些欄位在推論時真的拿得到，否則模型會虛高。",
                }
            )
        m = relevance.get("model") or {}
        if m.get("holdout_score") is not None:
            metric = "R²" if m["metric"] == "r2" else "accuracy"
            if m["holdout_score"] < (0.3 if m["metric"] == "r2" else 0.6):
                recommendations.append(
                    {
                        "level": "warn",
                        "text": f"隨機森林的保留集 {metric} 只有 {m['holdout_score']:.2f}："
                        "目前欄位對目標的預測力有限，建議補充特徵或確認標籤品質。",
                    }
                )
            else:
                recommendations.append(
                    {
                        "level": "info",
                        "text": f"隨機森林保留集 {metric} = {m['holdout_score']:.2f}，"
                        "可直接用 AutoML（XGBoost / 隨機森林候選）正式訓練。",
                    }
                )
        if task == "regression":
            lin = [f["name"] for f in relevance["features"][:5] if abs(float(f.get("corr_target") or 0)) > 0.6]
            if lin:
                recommendations.append(
                    {"level": "info", "text": f"{', '.join(lin)} 與目標呈強線性關係，tabular.linear 也值得當基準。"}
                )
    else:
        recommendations.append(
            {
                "level": "info",
                "text": "沒有指定目標欄位：只做了相關性與共線性分析；要看哪些欄位對預測有幫助，請填目標欄位再跑一次。",
            }
        )
    if len(df) < 200:
        recommendations.append(
            {"level": "warn", "text": f"只有 {len(df)} 列：統計量與重要度的變異會很大，結論請保守看待。"}
        )
    report["recommendations"] = recommendations
    tick(1.0)
    # finite(): the report is JSON for the backend and the browser, NaN / inf would fail the job at registration
    return finite(report)


def compact(report: dict[str, Any]) -> dict[str, Any]:
    """What goes into job.result (≤ 1 MB): everything except the big matrix beyond 25 columns."""
    out = dict(report)
    corr = dict(report.get("correlation") or {})
    cols = corr.get("columns") or []
    if len(cols) > 25:
        corr["columns"] = cols[:25]
        corr["matrix"] = [row[:25] for row in (corr.get("matrix") or [])[:25]]
        corr["truncated"] = True
    out["correlation"] = corr
    rel = dict(report.get("relevance") or {})
    rel["features"] = (rel.get("features") or [])[:40]
    out["relevance"] = rel
    out["columns"] = (report.get("columns") or [])[:80]
    return out
