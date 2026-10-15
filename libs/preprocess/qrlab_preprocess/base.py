"""Op base class, parameter specs and the registry.

An op is stateless (apply only) or fitted (fit on the training data, replay the same state at inference).
Data containers by data type: TABULAR / TEXT → pandas.DataFrame, SEQUENCE / SPECTRUM → np.ndarray (N, T, C),
IMAGE → list[PIL.Image.Image].
"""

from __future__ import annotations

import base64
import io
from dataclasses import dataclass, field
from typing import Any

import numpy as np


@dataclass(frozen=True)
class Param:
    name: str
    label: str
    type: str  # int | float | str | bool | choice | columns
    default: Any = None
    min: float | None = None
    max: float | None = None
    choices: tuple[Any, ...] = ()
    help: str = ""

    def coerce(self, value: Any) -> Any:
        if value is None:
            return self.default
        if self.type == "int":
            v = int(value)
        elif self.type == "float":
            v = float(value)
        elif self.type == "bool":
            v = value if isinstance(value, bool) else str(value).lower() in ("1", "true", "yes", "on")
        elif self.type == "choice":
            v = value
            if v not in self.choices:
                raise ValueError(f"{self.name}: 必須是 {list(self.choices)} 之一")
            return v
        elif self.type == "columns":
            if isinstance(value, str):
                v = [c.strip() for c in value.split(",") if c.strip()]
            else:
                v = [str(c) for c in value]
            return v
        else:
            v = str(value)
        if self.type in ("int", "float"):
            if self.min is not None and v < self.min:
                raise ValueError(f"{self.name}: 不能小於 {self.min}")
            if self.max is not None and v > self.max:
                raise ValueError(f"{self.name}: 不能大於 {self.max}")
        return v

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"name": self.name, "label": self.label, "type": self.type, "default": self.default}
        if self.min is not None:
            d["min"] = self.min
        if self.max is not None:
            d["max"] = self.max
        if self.choices:
            d["choices"] = list(self.choices)
        if self.help:
            d["help"] = self.help
        return d


@dataclass
class Context:
    data_type: str
    task_type: str | None = None
    protected: list[str] = field(default_factory=list)  # columns ops must never transform / drop (target, id)
    text_column: str = "text"


class Op:
    id: str = ""
    label: str = ""
    description: str = ""
    data_types: tuple[str, ...] = ()
    params: tuple[Param, ...] = ()
    geometric: bool = False  # changes pixel coordinates → not allowed with box / mask labels
    fitted: bool = False  # learns state from training data
    drops_rows: bool = False

    def __init__(self, **params: Any) -> None:
        spec = {p.name: p for p in self.params}
        unknown = set(params) - set(spec)
        if unknown:
            raise ValueError(f"{self.id}: 未知參數 {sorted(unknown)}")
        self.p: dict[str, Any] = {name: p.coerce(params.get(name)) for name, p in spec.items()}
        self.state: dict[str, Any] = {}

    def fit(self, data: Any, ctx: Context) -> None:
        """Learn state from training data (fitted ops only)."""

    def apply(self, data: Any, ctx: Context) -> Any:
        raise NotImplementedError

    def to_json(self) -> dict[str, Any]:
        return {"op": self.id, "params": self.p, "state": jsonable(self.state)}

    @classmethod
    def describe(cls) -> dict[str, Any]:
        return {
            "id": cls.id,
            "label": cls.label,
            "description": cls.description,
            "data_types": list(cls.data_types),
            "params": [p.to_dict() for p in cls.params],
            "geometric": cls.geometric,
            "fitted": cls.fitted,
            "drops_rows": cls.drops_rows,
        }


REGISTRY: dict[str, type[Op]] = {}


def register(cls: type[Op]) -> type[Op]:
    if not cls.id or cls.id in REGISTRY:
        raise RuntimeError(f"bad or duplicate op id: {cls.id!r}")
    REGISTRY[cls.id] = cls
    return cls


def jsonable(v: Any) -> Any:
    if isinstance(v, dict):
        return {str(k): jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [jsonable(x) for x in v]
    if isinstance(v, np.ndarray):
        return v.tolist()
    if isinstance(v, np.generic):
        return v.item()
    try:
        from PIL import Image

        if isinstance(v, Image.Image):
            buf = io.BytesIO()
            v.save(buf, format="PNG")
            return {"__png__": base64.b64encode(buf.getvalue()).decode("ascii")}
    except ImportError:
        pass
    return v


def unjson_image(v: Any):
    from PIL import Image

    if isinstance(v, dict) and "__png__" in v:
        return Image.open(io.BytesIO(base64.b64decode(v["__png__"])))
    return v
