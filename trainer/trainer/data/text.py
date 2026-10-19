from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


def read_text_table(input_dir: Path) -> pd.DataFrame:
    for pat in ("*.jsonl", "*.csv", "**/*.jsonl", "**/*.csv"):
        files = sorted(input_dir.glob(pat))
        if files:
            f = files[0]
            if f.suffix == ".jsonl":
                with f.open(encoding="utf-8") as fh:
                    return pd.DataFrame([json.loads(line) for line in fh if line.strip()])
            return pd.read_csv(f)
    raise FileNotFoundError(f"no jsonl/csv under {input_dir}")


def split_text(df: pd.DataFrame, spec: dict) -> tuple[pd.Series, pd.Series | None]:
    text_col = spec.get("text_column", "text")
    label_col = spec.get("label_column", "label")
    texts = df[text_col].astype(str)
    labels = df[label_col] if label_col in df.columns else None
    return texts, labels
