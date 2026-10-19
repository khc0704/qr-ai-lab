"""Tabular loading: csv / parquet → (X: DataFrame, y: Series | None); preprocessing pipeline builder."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from trainer.log import info


def find_table(input_dir: Path) -> Path:
    for pat in ("*.csv", "*.parquet", "**/*.csv", "**/*.parquet"):
        files = sorted(input_dir.glob(pat))
        if files:
            return files[0]
    raise FileNotFoundError(f"no csv/parquet under {input_dir}")


def read_table(path: Path) -> pd.DataFrame:
    if path.suffix == ".parquet":
        return pd.read_parquet(path)
    return pd.read_csv(path)


def split_xy(df: pd.DataFrame, spec: dict) -> tuple[pd.DataFrame, pd.Series | None]:
    target = spec.get("target")
    features = spec.get("features")
    if isinstance(features, str):
        features = [c.strip() for c in features.split(",") if c.strip()]
    y = None
    if target:
        if target not in df.columns:
            raise KeyError(f"target column '{target}' not in {list(df.columns)[:20]}")
        y = df[target]
        X = df.drop(columns=[target])
    else:
        X = df
    if features:
        X = X[[c for c in features if c in X.columns]]
    drop = spec.get("drop_columns") or []
    X = X.drop(columns=[c for c in drop if c in X.columns])
    info(f"prepare: {len(X):,} rows × {X.shape[1]} columns" + (f", target={target}" if target else ""))
    return X, y


def preprocessor(X: pd.DataFrame, spec: dict) -> ColumnTransformer:
    cat_cols = spec.get("categorical")
    if isinstance(cat_cols, str):
        cat_cols = [c.strip() for c in cat_cols.split(",") if c.strip()]
    if not cat_cols:
        cat_cols = [c for c in X.columns if not pd.api.types.is_numeric_dtype(X[c])]
    num_cols = [c for c in X.columns if c not in cat_cols and pd.api.types.is_numeric_dtype(X[c])]
    return ColumnTransformer(
        [
            ("num", Pipeline([("impute", SimpleImputer(strategy="median")), ("scale", StandardScaler())]), num_cols),
            ("cat", Pipeline([("impute", SimpleImputer(strategy="most_frequent")), ("onehot", OneHotEncoder(handle_unknown="ignore", sparse_output=False))]), cat_cols),
        ],
        remainder="drop",
    )
