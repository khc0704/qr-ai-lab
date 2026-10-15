from __future__ import annotations

from typing import Any

import qrlab_preprocess
from fastapi import APIRouter

from app.catalog import loader
from app.core.deps import CurrentUser

router = APIRouter(tags=["catalog"])


@router.get("/catalog", summary="資料類型、任務、模型家族、搜尋空間、AutoML 規則")
async def catalog(_: CurrentUser) -> dict[str, Any]:
    return loader.public_catalog()


@router.get("/catalog/preprocess", summary="可用的資料前處理步驟與參數（依 data_type 篩選）")
async def preprocess_catalog(_: CurrentUser, data_type: str | None = None) -> list[dict[str, Any]]:
    return qrlab_preprocess.catalog(data_type)
