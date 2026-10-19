from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

DataType = Literal["TABULAR", "IMAGE", "SEQUENCE", "TEXT", "SPECTRUM"]


class ToolUploadRead(BaseModel):
    """A file in the standalone preprocessing tool: lives under DATA_ROOT/tools/<id>/ until downloaded or expired.
    Nothing about it is written to the database."""

    id: str
    data_type: DataType
    original_filename: str
    size_bytes: int
    format: str
    detected_spec: dict[str, Any] | None = None
    expires_at: datetime
    created_at: datetime


class ToolProcessBody(BaseModel):
    steps: list[dict[str, Any]] = Field(default_factory=list, max_length=20)
    spec: dict[str, Any] = Field(default_factory=dict)
    task_type: str | None = None
    name: str | None = Field(default=None, max_length=120)


class ToolPreviewBody(ToolProcessBody):
    sample: int = Field(default=5, ge=1, le=50)


class PreviewTopValue(BaseModel):
    value: str
    count: int


class PreviewColumnStat(BaseModel):
    """One column of a tabular / text preview (the input sample or the pipeline output), for a spreadsheet-like
    header: kind, missing share, cardinality, numeric range or the most frequent values."""

    name: str
    dtype: Literal["number", "text", "bool", "datetime"]
    missing: int
    missing_ratio: float
    unique: int
    min: float | str | None = None  # number → float; datetime → ISO string
    max: float | str | None = None
    mean: float | None = None  # number only
    top: list[PreviewTopValue] = Field(default_factory=list)  # text / bool: up to 5 most frequent values


class PreviewStep(BaseModel):
    op: str
    label: str
    params: dict[str, Any]
    fitted: bool
    warnings: list[str]  # e.g. 「欄位 X：87% 的值無法轉成數字，會變成缺值」


class PreviewRead(BaseModel):
    """Before / after sample of a preprocessing pipeline. ``steps`` / ``before`` / ``after`` are the original
    fields (their content depends on data_type); ``step_details`` adds per-step warnings; TABULAR / TEXT previews
    also carry row counts and per-column statistics for the input sample and for the output of the whole
    pipeline."""

    data_type: DataType
    steps: list[str]
    step_details: list[PreviewStep]
    warnings: list[str]  # step_details[*].warnings flattened, each prefixed with 「步驟 n（label）」
    before: dict[str, Any]
    after: dict[str, Any]
    rows_in: int | None = None
    rows_out: int | None = None
    columns_in: list[PreviewColumnStat] | None = None
    columns_out: list[PreviewColumnStat] | None = None


class ToolAnalyzeBody(BaseModel):
    """Start an analysis job on a tool upload. tabular_profile: correlations, collinearity (VIF), relevance to the
    target, recommendations. image_quality: IQA metrics per image, drift across groups (folders), embeddings."""

    analysis: Literal["tabular_profile", "image_quality"]
    params: dict[str, Any] = Field(default_factory=dict)
    name: str | None = Field(default=None, max_length=120)
