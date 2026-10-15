"""Text ops: operate on the text column of a DataFrame so labels stay aligned when rows are dropped."""

from __future__ import annotations

import re

import pandas as pd

from qrlab_preprocess.base import Context, Op, Param, register

TEXT = ("TEXT",)


def _col(df: pd.DataFrame, ctx: Context) -> str:
    if ctx.text_column not in df.columns:
        raise ValueError(f"找不到文字欄位 {ctx.text_column}")
    return ctx.text_column


class _TextMap(Op):
    data_types = TEXT

    def transform_text(self, s: pd.Series) -> pd.Series:
        raise NotImplementedError

    def apply(self, df: pd.DataFrame, ctx: Context) -> pd.DataFrame:
        c = _col(df, ctx)
        out = df.copy()
        out[c] = self.transform_text(out[c].astype(str))
        return out


@register
class Lowercase(_TextMap):
    id = "text.lowercase"
    label = "轉小寫"

    def transform_text(self, s: pd.Series) -> pd.Series:
        return s.str.lower()


@register
class StripWhitespace(_TextMap):
    id = "text.strip_whitespace"
    label = "清理空白"
    description = "去頭尾空白，連續空白合併成一個。"

    def transform_text(self, s: pd.Series) -> pd.Series:
        return s.str.replace(r"\s+", " ", regex=True).str.strip()


@register
class RemovePunctuation(_TextMap):
    id = "text.remove_punctuation"
    label = "移除標點"

    def transform_text(self, s: pd.Series) -> pd.Series:
        return s.str.replace(r"[^\w\s一-鿿]", " ", regex=True)


@register
class RemoveUrls(_TextMap):
    id = "text.remove_urls"
    label = "移除網址"

    def transform_text(self, s: pd.Series) -> pd.Series:
        return s.str.replace(r"https?://\S+|www\.\S+", " ", regex=True)


@register
class RemoveNumbers(_TextMap):
    id = "text.remove_numbers"
    label = "移除數字"

    def transform_text(self, s: pd.Series) -> pd.Series:
        return s.str.replace(r"\d+", " ", regex=True)


@register
class Truncate(_TextMap):
    id = "text.truncate"
    label = "截斷長度"
    params = (Param("max_chars", "最多字元", "int", default=512, min=8, max=100000),)

    def transform_text(self, s: pd.Series) -> pd.Series:
        return s.str.slice(0, self.p["max_chars"])


@register
class ReplaceRegex(_TextMap):
    id = "text.replace_regex"
    label = "正規表達式取代"
    params = (
        Param("pattern", "樣式", "str", default=""),
        Param("replacement", "取代為", "str", default=""),
    )

    def __init__(self, **params) -> None:
        super().__init__(**params)
        if len(self.p["pattern"]) > 200:
            raise ValueError("pattern 太長")
        try:
            re.compile(self.p["pattern"])
        except re.error as e:
            raise ValueError(f"pattern 無效：{e}") from e

    def transform_text(self, s: pd.Series) -> pd.Series:
        return s.str.replace(self.p["pattern"], self.p["replacement"], regex=True)


@register
class DropEmpty(Op):
    id = "text.drop_empty"
    label = "刪除空白文字"
    data_types = TEXT
    drops_rows = True

    def apply(self, df: pd.DataFrame, ctx: Context) -> pd.DataFrame:
        c = _col(df, ctx)
        return df[df[c].astype(str).str.strip() != ""].reset_index(drop=True)


@register
class Dedupe(Op):
    id = "text.dedupe"
    label = "刪除重複文字"
    data_types = TEXT
    drops_rows = True

    def apply(self, df: pd.DataFrame, ctx: Context) -> pd.DataFrame:
        c = _col(df, ctx)
        return df.drop_duplicates(subset=[c]).reset_index(drop=True)
