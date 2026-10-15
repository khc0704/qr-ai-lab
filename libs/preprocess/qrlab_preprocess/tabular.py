"""Tabular (and shared row-level) ops on pandas DataFrames."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from qrlab_preprocess.base import Context, Op, Param, register

TAB = ("TABULAR",)
TAB_TEXT = ("TABULAR", "TEXT")


def _numeric_columns(df: pd.DataFrame, ctx: Context, selected: list[str]) -> list[str]:
    cols = selected or [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c]) and c not in ctx.protected]
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise ValueError(f"找不到欄位 {missing}")
    return [c for c in cols if c not in ctx.protected]


@register
class DropMissing(Op):
    id = "tabular.drop_missing"
    label = "刪除含缺值的列"
    description = "刪除指定欄位（預設全部）有缺值的列。"
    data_types = TAB_TEXT
    drops_rows = True
    params = (
        Param("columns", "檢查的欄位", "columns", default=[], help="留空 = 全部欄位"),
        Param(
            "how",
            "條件",
            "choice",
            default="any",
            choices=("any", "all"),
            help="any：任一欄缺值就刪；all：全部缺值才刪",
        ),
    )

    def apply(self, df: pd.DataFrame, ctx: Context) -> pd.DataFrame:
        cols = self.p["columns"] or list(df.columns)
        return df.dropna(subset=[c for c in cols if c in df.columns], how=self.p["how"]).reset_index(drop=True)


@register
class Impute(Op):
    id = "tabular.impute"
    label = "補值"
    description = "數值欄用中位數 / 平均數，類別欄用眾數，或填固定值；補值用的數字在訓練時學到，推論沿用。"
    data_types = TAB
    fitted = True
    params = (
        Param("strategy", "策略", "choice", default="median", choices=("median", "mean", "most_frequent", "constant")),
        Param("columns", "欄位", "columns", default=[], help="留空 = 全部非目標欄位"),
        Param("fill_value", "固定值", "str", default="0", help="strategy=constant 時使用"),
    )

    def fit(self, df: pd.DataFrame, ctx: Context) -> None:
        cols = self.p["columns"] or [c for c in df.columns if c not in ctx.protected]
        values: dict[str, Any] = {}
        for c in cols:
            if c not in df.columns:
                raise ValueError(f"找不到欄位 {c}")
            s = df[c]
            strat = self.p["strategy"]
            if strat == "constant":
                values[c] = float(self.p["fill_value"]) if pd.api.types.is_numeric_dtype(s) else self.p["fill_value"]
            elif pd.api.types.is_numeric_dtype(s) and strat in ("median", "mean"):
                values[c] = float(s.median() if strat == "median" else s.mean()) if s.notna().any() else 0.0
            else:
                mode = s.mode(dropna=True)
                values[c] = mode.iloc[0] if len(mode) else ""
        self.state = {"values": values}

    def apply(self, df: pd.DataFrame, ctx: Context) -> pd.DataFrame:
        values = {c: v for c, v in self.state.get("values", {}).items() if c in df.columns}
        return df.fillna(value=values)


@register
class DropColumns(Op):
    id = "tabular.drop_columns"
    label = "移除欄位"
    data_types = TAB_TEXT
    params = (Param("columns", "欄位", "columns", default=[]),)

    def apply(self, df: pd.DataFrame, ctx: Context) -> pd.DataFrame:
        return df.drop(columns=[c for c in self.p["columns"] if c in df.columns and c not in ctx.protected])


@register
class KeepColumns(Op):
    id = "tabular.keep_columns"
    label = "只保留欄位"
    description = "目標欄與 id 欄一定保留。"
    data_types = TAB_TEXT
    params = (Param("columns", "欄位", "columns", default=[]),)

    def apply(self, df: pd.DataFrame, ctx: Context) -> pd.DataFrame:
        keep = [c for c in df.columns if c in self.p["columns"] or c in ctx.protected]
        return df[keep]


@register
class DropDuplicates(Op):
    id = "tabular.drop_duplicates"
    label = "刪除重複列"
    data_types = TAB_TEXT
    drops_rows = True
    params = (Param("columns", "比對的欄位", "columns", default=[], help="留空 = 全部欄位"),)

    def apply(self, df: pd.DataFrame, ctx: Context) -> pd.DataFrame:
        cols = [c for c in self.p["columns"] if c in df.columns] or None
        return df.drop_duplicates(subset=cols).reset_index(drop=True)


@register
class ClipOutliers(Op):
    id = "tabular.clip_outliers"
    label = "離群值處理"
    description = "IQR 或 z-score 定義上下界（訓練時學到），超出的值截斷到邊界或整列刪除。"
    data_types = TAB
    fitted = True
    drops_rows = True  # when action=drop
    params = (
        Param("method", "方法", "choice", default="iqr", choices=("iqr", "zscore")),
        Param(
            "factor",
            "倍數",
            "float",
            default=1.5,
            min=0.1,
            max=20,
            help="IQR 倍數（常用 1.5）或 z-score 門檻（常用 3）",
        ),
        Param("action", "動作", "choice", default="clip", choices=("clip", "drop")),
        Param("columns", "欄位", "columns", default=[], help="留空 = 全部數值欄"),
    )

    def fit(self, df: pd.DataFrame, ctx: Context) -> None:
        bounds: dict[str, list[float]] = {}
        for c in _numeric_columns(df, ctx, self.p["columns"]):
            s = pd.to_numeric(df[c], errors="coerce").dropna()
            if s.empty:
                continue
            if self.p["method"] == "iqr":
                q1, q3 = float(s.quantile(0.25)), float(s.quantile(0.75))
                iqr = q3 - q1
                bounds[c] = [q1 - self.p["factor"] * iqr, q3 + self.p["factor"] * iqr]
            else:
                m, sd = float(s.mean()), float(s.std() or 0.0)
                bounds[c] = [m - self.p["factor"] * sd, m + self.p["factor"] * sd]
        self.state = {"bounds": bounds}

    def apply(self, df: pd.DataFrame, ctx: Context) -> pd.DataFrame:
        bounds = {c: b for c, b in self.state.get("bounds", {}).items() if c in df.columns}
        if not bounds:
            return df
        if self.p["action"] == "clip":
            out = df.copy()
            for c, (lo, hi) in bounds.items():
                out[c] = pd.to_numeric(out[c], errors="coerce").clip(lo, hi)
            return out
        mask = pd.Series(True, index=df.index)
        for c, (lo, hi) in bounds.items():
            v = pd.to_numeric(df[c], errors="coerce")
            mask &= v.isna() | ((v >= lo) & (v <= hi))
        return df[mask].reset_index(drop=True)


@register
class Standardize(Op):
    id = "tabular.standardize"
    label = "標準化（z-score）"
    description = "(x − 平均) / 標準差；平均與標準差在訓練時學到。"
    data_types = TAB
    fitted = True
    params = (Param("columns", "欄位", "columns", default=[], help="留空 = 全部數值欄"),)

    def fit(self, df: pd.DataFrame, ctx: Context) -> None:
        stats = {}
        for c in _numeric_columns(df, ctx, self.p["columns"]):
            s = pd.to_numeric(df[c], errors="coerce")
            stats[c] = [float(s.mean()), float(s.std() or 1.0) or 1.0]
        self.state = {"stats": stats}

    def apply(self, df: pd.DataFrame, ctx: Context) -> pd.DataFrame:
        out = df.copy()
        for c, (m, sd) in self.state.get("stats", {}).items():
            if c in out.columns:
                out[c] = (pd.to_numeric(out[c], errors="coerce") - m) / (sd or 1.0)
        return out


@register
class MinMax(Op):
    id = "tabular.minmax"
    label = "歸一化（0–1）"
    description = "(x − min) / (max − min)；min / max 在訓練時學到。"
    data_types = TAB
    fitted = True
    params = (Param("columns", "欄位", "columns", default=[], help="留空 = 全部數值欄"),)

    def fit(self, df: pd.DataFrame, ctx: Context) -> None:
        stats = {}
        for c in _numeric_columns(df, ctx, self.p["columns"]):
            s = pd.to_numeric(df[c], errors="coerce")
            lo, hi = float(s.min()), float(s.max())
            stats[c] = [lo, hi if hi > lo else lo + 1.0]
        self.state = {"stats": stats}

    def apply(self, df: pd.DataFrame, ctx: Context) -> pd.DataFrame:
        out = df.copy()
        for c, (lo, hi) in self.state.get("stats", {}).items():
            if c in out.columns:
                out[c] = (pd.to_numeric(out[c], errors="coerce") - lo) / (hi - lo)
        return out


@register
class SymLog(Op):
    id = "tabular.log"
    label = "對數轉換"
    description = "sign(x)·log(1+|x|)，壓縮長尾分布。"
    data_types = TAB
    params = (Param("columns", "欄位", "columns", default=[], help="留空 = 全部數值欄"),)

    def apply(self, df: pd.DataFrame, ctx: Context) -> pd.DataFrame:
        out = df.copy()
        for c in _numeric_columns(df, ctx, self.p["columns"]):
            v = pd.to_numeric(out[c], errors="coerce")
            out[c] = np.sign(v) * np.log1p(np.abs(v))
        return out


@register
class ToNumeric(Op):
    id = "tabular.to_numeric"
    label = "轉成數值"
    description = "把文字欄轉成數字，轉不了的變成缺值（之後可補值）。"
    data_types = TAB
    params = (Param("columns", "欄位", "columns", default=[], help="留空 = 全部非數值欄"),)

    def apply(self, df: pd.DataFrame, ctx: Context) -> pd.DataFrame:
        out = df.copy()
        cols = self.p["columns"] or [c for c in df.columns if not pd.api.types.is_numeric_dtype(df[c])]
        for c in cols:
            if c in out.columns and c not in ctx.protected:
                out[c] = pd.to_numeric(out[c], errors="coerce")
        return out


@register
class FilterRows(Op):
    id = "tabular.filter_rows"
    label = "篩選列"
    description = "只保留符合條件的列，例如 line == A、temp > 300、lot in L1,L2。"
    data_types = TAB_TEXT
    drops_rows = True
    params = (
        Param("column", "欄位", "str", default=""),
        Param(
            "operator",
            "條件",
            "choice",
            default="==",
            choices=("==", "!=", ">", ">=", "<", "<=", "in", "not_in", "contains"),
        ),
        Param("value", "值", "str", default="", help="in / not_in 用逗號分隔多個值"),
    )

    def apply(self, df: pd.DataFrame, ctx: Context) -> pd.DataFrame:
        c, op, raw = self.p["column"], self.p["operator"], self.p["value"]
        if c not in df.columns:
            raise ValueError(f"找不到欄位 {c}")
        s = df[c]
        if op in ("in", "not_in"):
            vals = [v.strip() for v in raw.split(",")]
            mask = s.astype(str).isin(vals)
            mask = ~mask if op == "not_in" else mask
        elif op == "contains":
            mask = s.astype(str).str.contains(raw, regex=False, na=False)
        else:
            try:
                val: Any = float(raw)
                v = pd.to_numeric(s, errors="coerce")
            except ValueError:
                val, v = raw, s.astype(str)
            mask = {"==": v == val, "!=": v != val, ">": v > val, ">=": v >= val, "<": v < val, "<=": v <= val}[op]
        return df[mask.fillna(False)].reset_index(drop=True)
