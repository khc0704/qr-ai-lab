"""Offline model zoo: pretrained weights are files the admin placed under MODEL_ZOO_ROOT. Nothing is downloaded."""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

OFFLINE_ENV = {
    "HF_HUB_OFFLINE": "1",
    "TRANSFORMERS_OFFLINE": "1",
    "HF_DATASETS_OFFLINE": "1",
    "YOLO_OFFLINE": "1",
    "ULTRALYTICS_OFFLINE": "1",
}


def force_offline() -> None:
    for k, v in OFFLINE_ENV.items():
        os.environ.setdefault(k, v)


def resolver(zoo_root: Path | None, zoo_weights: dict[str, str]) -> Callable[[str], Path]:
    """Returns weight_id → local path. zoo_weights (from the job spec) maps ids to file names under the zoo."""

    def resolve(weight_id: str) -> Path:
        if zoo_root is None:
            raise FileNotFoundError(
                f"需要預訓練權重 '{weight_id}'，但模型庫（MODEL_ZOO_ROOT）未掛載。"
                "請管理員用 scripts/fetch_model_zoo.py 準備權重。"
            )
        name = zoo_weights.get(weight_id, weight_id).rstrip("/")
        path = zoo_root / name
        if not path.exists():
            raise FileNotFoundError(
                f"模型庫缺少權重 '{weight_id}'（預期位置 {path}）。"
                "本服務不會自動下載模型；請管理員在有網路的機器執行 scripts/fetch_model_zoo.py，"
                "再把檔案放到伺服器的 MODEL_ZOO_ROOT。"
            )
        return path

    return resolve
