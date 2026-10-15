"""qrlab_preprocess: user-selectable preprocessing steps, previewed on samples in the backend, fitted on the
training data by the trainer and replayed unchanged at inference.

    steps = [{"op": "tabular.impute", "params": {"strategy": "median"}}, {"op": "tabular.standardize"}]
    pipe = Pipeline.from_spec("TABULAR", steps, protected=["yield_pct"])
    train_df = pipe.fit_transform(train_df)          # learns impute values / mean / std
    state = pipe.to_json()                            # stored with the model
    test_df = Pipeline.from_json("TABULAR", state).transform(test_df)
"""

from __future__ import annotations

from typing import Any

from qrlab_preprocess import image, sequence, tabular, text  # noqa: F401  (registers the ops)
from qrlab_preprocess.base import REGISTRY, Context, Op, jsonable

__all__ = ["REGISTRY", "Context", "Op", "Pipeline", "catalog", "validate"]

DATA_TYPES = ("TABULAR", "IMAGE", "SEQUENCE", "TEXT", "SPECTRUM")
MAX_STEPS = 20


def catalog(data_type: str | None = None) -> list[dict[str, Any]]:
    """Op descriptions for the UI (grouped by the caller)."""
    out = []
    for op in REGISTRY.values():
        if data_type is None or data_type in op.data_types:
            out.append(op.describe())
    return out


def _build(step: dict[str, Any]) -> Op:
    if not isinstance(step, dict) or not step.get("op"):
        raise ValueError("每個步驟需要 op")
    cls = REGISTRY.get(step["op"])
    if cls is None:
        raise ValueError(f"未知的前處理 {step['op']}")
    params = step.get("params") or {}
    if not isinstance(params, dict):
        raise ValueError(f"{step['op']}: params 必須是物件")
    return cls(**params)


def validate(data_type: str, task_type: str | None, steps: list[dict[str, Any]] | None) -> list[Op]:
    """Build the ops or raise ValueError with a user-facing message."""
    if not steps:
        return []
    if data_type not in DATA_TYPES:
        raise ValueError(f"未知的 data_type {data_type}")
    if len(steps) > MAX_STEPS:
        raise ValueError(f"最多 {MAX_STEPS} 個前處理步驟")
    ops = []
    for i, step in enumerate(steps, 1):
        try:
            op = _build(step)
        except (ValueError, TypeError) as e:
            raise ValueError(f"步驟 {i}：{e}") from e
        if data_type not in op.data_types:
            raise ValueError(f"步驟 {i}：{op.id} 不適用於 {data_type}")
        if op.geometric and task_type in ("detection", "segmentation"):
            raise ValueError(f"步驟 {i}：{op.label} 會改變座標，偵測 / 分割的標註會失效，請改用不改變幾何的處理")
        ops.append(op)
    return ops


class Pipeline:
    def __init__(self, data_type: str, ops: list[Op], ctx: Context | None = None) -> None:
        self.data_type = data_type
        self.ops = ops
        self.ctx = ctx or Context(data_type=data_type)

    @classmethod
    def from_spec(
        cls,
        data_type: str,
        steps: list[dict[str, Any]] | None,
        *,
        task_type: str | None = None,
        protected: list[str] | None = None,
        text_column: str = "text",
    ) -> Pipeline:
        ops = validate(data_type, task_type, steps)
        return cls(data_type, ops, Context(data_type, task_type, list(protected or []), text_column))

    @classmethod
    def from_json(
        cls,
        data_type: str,
        steps: list[dict[str, Any]],
        *,
        protected: list[str] | None = None,
        text_column: str = "text",
    ) -> Pipeline:
        ops = []
        for step in steps:
            op = _build(step)
            op.state = dict(step.get("state") or {})
            ops.append(op)
        return cls(data_type, ops, Context(data_type, None, list(protected or []), text_column))

    def __len__(self) -> int:
        return len(self.ops)

    def fit_transform(self, data: Any) -> Any:
        for op in self.ops:
            if op.fitted:
                op.fit(data, self.ctx)
            data = op.apply(data, self.ctx)
        return data

    def transform(self, data: Any) -> Any:
        for op in self.ops:
            data = op.apply(data, self.ctx)
        return data

    def to_json(self) -> list[dict[str, Any]]:
        return [jsonable(op.to_json()) for op in self.ops]

    def describe(self) -> list[str]:
        return [f"{op.label}" + (f" {op.p}" if op.p else "") for op in self.ops]
