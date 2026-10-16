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


MAX_PATTERN_LEN = 200


def _repeat_depth(nodes, depth: int = 0) -> int:
    """Deepest nesting of repeat operators in a parsed pattern (``(a+)+`` → 2, ``a+b*`` → 1)."""
    parser = re._parser  # the stdlib's own parser; the tree is what re.compile uses
    deepest = depth
    for op, av in nodes:
        if op in (parser.MAX_REPEAT, parser.MIN_REPEAT, parser.POSSESSIVE_REPEAT):
            _lo, hi, body = av
            inner = 1 if (hi == parser.MAXREPEAT or hi > 1) else 0
            deepest = max(deepest, _repeat_depth(body, depth + inner))
        elif op == parser.SUBPATTERN:
            deepest = max(deepest, _repeat_depth(av[3], depth))
        elif op == parser.BRANCH:
            for branch in av[1]:
                deepest = max(deepest, _repeat_depth(branch, depth))
        elif op in (parser.ASSERT, parser.ASSERT_NOT):
            deepest = max(deepest, _repeat_depth(av[1], depth))
        elif op == parser.ATOMIC_GROUP:
            deepest = max(deepest, _repeat_depth(av, depth))
    return deepest


def check_regex(pattern: str) -> None:
    """Reject patterns that can backtrack catastrophically: a repeated group that itself contains a repeat,
    e.g. ``(a+)+``, ``(a*)*``, ``(a|b+)*``, ``(a{2,})+``. Previews run in the API process."""
    if len(pattern) > MAX_PATTERN_LEN:
        raise ValueError(f"pattern 太長（最多 {MAX_PATTERN_LEN} 字元）")
    try:
        tree = re._parser.parse(pattern)
        re.compile(pattern)
    except re.error as e:
        raise ValueError(f"pattern 無效：{e}") from e
    if _repeat_depth(tree) > 1:
        raise ValueError("pattern 含巢狀量詞（例如 (a+)+、(a*)*、(a{2,})+），可能造成災難性回溯，請改寫")


@register
class ReplaceRegex(_TextMap):
    id = "text.replace_regex"
    label = "正規表達式取代"
    description = "Python 正規表達式；為避免災難性回溯，不接受巢狀量詞（如 (a+)+、(a*)*、(a{2,})+）。"
    params = (
        Param(
            "pattern",
            "樣式",
            "str",
            default="",
            help=f"Python 正規表達式，最多 {MAX_PATTERN_LEN} 字元；不接受巢狀量詞（(a+)+、(a*)*、(a{{2,}})+ 等）",
        ),
        Param("replacement", "取代為", "str", default=""),
    )

    def __init__(self, **params) -> None:
        super().__init__(**params)
        check_regex(self.p["pattern"])

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
