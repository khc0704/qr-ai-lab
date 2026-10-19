"""NaN / ±inf never reach the backend or a report file: finite() turns them into null, dumps() refuses the rest."""

from __future__ import annotations

import json

import numpy as np
import pytest

from trainer import jsonsafe


def test_finite_walks_containers_and_converts_numpy():
    src = {
        "score": float("nan"),
        "nested": [1.0, float("inf"), (np.float32("-inf"), np.float64(2.5))],
        "arr": np.array([1.0, np.nan]),
        "i": np.int64(3),
        "b": np.bool_(True),
        "flag": False,
        "s": "x",
        "n": None,
        np.str_("k"): np.float32(1.5),
    }
    out = jsonsafe.finite(src)
    assert out == {
        "score": None,
        "nested": [1.0, None, [None, 2.5]],
        "arr": [1.0, None],
        "i": 3,
        "b": True,
        "flag": False,
        "s": "x",
        "n": None,
        "k": 1.5,
    }
    assert type(out["i"]) is int and type(out["b"]) is bool and type(out["k"]) is float and type(out["flag"]) is bool
    json.dumps(out, allow_nan=False)
    assert src["score"] != src["score"]  # the input is copied, not mutated


def test_dumps_replaces_non_finite_and_is_loud_otherwise():
    assert json.loads(jsonsafe.dumps({"a": float("nan"), "b": (1, 2), "c": "中"})) == {
        "a": None,
        "b": [1, 2],
        "c": "中",
    }
    assert "中" in jsonsafe.dumps({"c": "中"})  # ensure_ascii=False by default
    with pytest.raises(ValueError, match="JSON compliant"):
        json.dumps({"a": float("nan")}, allow_nan=False)  # what the backend / a regression would hit
