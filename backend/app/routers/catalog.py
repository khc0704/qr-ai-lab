from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.catalog import loader
from app.core.deps import CurrentUser

router = APIRouter(tags=["catalog"])


@router.get("/catalog", summary="資料類型、任務、模型家族、搜尋空間、AutoML 規則")
async def catalog(_: CurrentUser) -> dict[str, Any]:
    return loader.public_catalog()
