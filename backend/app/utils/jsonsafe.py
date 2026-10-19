"""JSON-safe payloads: ``NaN`` / ``±inf`` become ``None``.

Python's ``json`` parser accepts the non-standard ``NaN`` / ``Infinity`` tokens, so a trainer that reports a
degenerate statistic reaches the service layer as a float NaN. FastAPI serialises responses with
``allow_nan=False`` and MariaDB's JSON columns reject the tokens, so every trainer-supplied payload is passed
through :func:`finite` before it is stored or echoed: a NaN from any trainer version becomes ``null`` instead of
a 500 that fails the job.
"""

from __future__ import annotations

import math
from typing import Any


def finite(obj: Any) -> Any:
    """Recursively copy ``obj`` (dict / list / tuple) with non-finite floats replaced by ``None``.

    Tuples come back as lists (what JSON makes of them anyway); everything else is returned unchanged.
    """
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {k: finite(v) for k, v in obj.items()}
    if isinstance(obj, list | tuple):
        return [finite(v) for v in obj]
    return obj
