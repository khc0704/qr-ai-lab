from __future__ import annotations

from typing import Any

import qrlab_preprocess
from fastapi import APIRouter

from app.catalog import loader
from app.core.deps import CurrentUser, DbSession
from app.schemas.admin import CapacityRead
from app.services import model_zoo as zoo_svc
from app.services import node as node_svc
from app.services import settings as settings_svc

router = APIRouter(tags=["catalog"])


@router.get("/catalog", summary="資料類型、任務、模型家族、搜尋空間、AutoML 規則")
async def catalog(_: CurrentUser) -> dict[str, Any]:
    """目錄加上每個家族的 `weights_ready`：需要的預訓練權重是否都已在模型庫（缺的話精靈會提示）。"""
    cat = loader.public_catalog()
    ready = zoo_svc.families_ready()
    for fid, fam in cat["families"].items():
        fam["weights_ready"] = ready.get(fid, True)
    return cat


@router.get("/catalog/preprocess", summary="可用的資料前處理步驟與參數（依 data_type 篩選）")
async def preprocess_catalog(_: CurrentUser, data_type: str | None = None) -> list[dict[str, Any]]:
    return qrlab_preprocess.catalog(data_type)


@router.get("/capacity", response_model=CapacityRead, summary="總資源池與目前已配置量（所有登入者可讀，申請表單用）")
async def capacity(session: DbSession, _: CurrentUser) -> CapacityRead:
    return CapacityRead(pool=await settings_svc.get_resource_pool(session), allocated=await node_svc.allocated(session))
