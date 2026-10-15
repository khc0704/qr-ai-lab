from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Env:
    job_id: int
    job_kind: str
    token: str
    backend_url: str
    input_dir: Path
    output_dir: Path
    model_dir: Path | None
    zoo_root: Path | None
    data_source: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_environ(cls) -> Env:
        e = os.environ
        ds = {k[len("DATA_SOURCE_") :].lower(): v for k, v in e.items() if k.startswith("DATA_SOURCE_")}
        if "headers" in ds:
            try:
                ds["headers"] = json.loads(ds["headers"] or "{}")  # type: ignore[assignment]
            except json.JSONDecodeError:
                ds["headers"] = {}  # type: ignore[assignment]
        return cls(
            job_id=int(e["JOB_ID"]),
            job_kind=e.get("JOB_KIND", "train"),
            token=e["JOB_TOKEN"],
            backend_url=e.get("BACKEND_URL", "http://localhost:8000").rstrip("/"),
            input_dir=Path(e.get("JOB_INPUT_DIR") or "/job/input"),
            output_dir=Path(e.get("JOB_OUTPUT_DIR") or "/job/output"),
            model_dir=Path(e["JOB_MODEL_DIR"])
            if e.get("JOB_MODEL_DIR")
            else (Path("/job/model") if Path("/job/model").exists() else None),
            zoo_root=Path(e["MODEL_ZOO_ROOT"])
            if e.get("MODEL_ZOO_ROOT")
            else (Path("/job/zoo") if Path("/job/zoo").exists() else None),
            data_source=ds if ds.get("kind") else {},
        )
