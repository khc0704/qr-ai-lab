"""JSON-safe payloads: ``NaN`` / ``±inf`` become ``null``, numpy scalars become Python numbers.

Everything the trainer sends to the backend (metrics, artifact metadata, result) and every report JSON it writes
to disk goes through :func:`finite`, so a degenerate statistic (MAD of 0, an all-NaN column, a silhouette on one
sample) can never fail the job: the backend serialises its responses with ``allow_nan=False`` and would answer
500 to a payload containing ``NaN``. :func:`dumps` is ``json.dumps`` with the same guard turned into an error, so
a NaN that slips past :func:`finite` is loud in tests instead of silently written to a file.
"""

from __future__ import annotations

import json
import math
from typing import Any

import numpy as np


def finite(obj: Any) -> Any:
    """Recursively copy ``obj`` (dict / list / tuple / ndarray) with non-finite floats replaced by ``None``.

    numpy scalars are converted to their Python equivalents (``np.float32`` → ``float``, ``np.int64`` → ``int``,
    ``np.bool_`` → ``bool``); tuples and arrays come back as lists, which is what JSON would make of them anyway.
    Anything else (str, int, bool, None, Path, …) is returned unchanged.
    """
    if isinstance(obj, bool | np.bool_):
        return bool(obj)
    if isinstance(obj, float | np.floating):
        v = float(obj)
        return v if math.isfinite(v) else None
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.ndarray):
        return finite(obj.tolist())
    if isinstance(obj, dict):
        return {_key(k): finite(v) for k, v in obj.items()}
    if isinstance(obj, list | tuple):
        return [finite(v) for v in obj]
    return obj


def _key(k: Any) -> Any:
    if isinstance(k, np.generic):
        return k.item()
    return k


def dumps(obj: Any, **kwargs: Any) -> str:
    """``json.dumps(finite(obj), ensure_ascii=False, allow_nan=False, **kwargs)``."""
    kwargs.setdefault("ensure_ascii", False)
    return json.dumps(finite(obj), allow_nan=False, **kwargs)
