"""Standalone data tools (no project needed). Preview is real time on a sample; the heavy work is a job in the
shared tool pool so it goes through the queue, resource limits, logs and cleanup like any job."""

from __future__ import annotations

from fastapi import APIRouter, File, Form, UploadFile

from app.core.deps import CurrentUser, DbSession
from app.routers import _serialize as ser
from app.schemas.common import Ok
from app.schemas.job import JobRead
from app.schemas.settings import ToolPoolStatus
from app.schemas.tools import PreviewRead, ToolAnalyzeBody, ToolPreviewBody, ToolProcessBody, ToolUploadRead
from app.services import tools as tools_svc

router = APIRouter(prefix="/tools", tags=["tools"])


@router.get("/pool", response_model=ToolPoolStatus, summary="工具池配額與我目前排隊 / 執行中的工具任務數")
async def pool(session: DbSession, user: CurrentUser) -> ToolPoolStatus:
    return await tools_svc.pool_status(session, user)


@router.get("/jobs", response_model=list[JobRead], summary="我的工具任務（前處理 / 分析）")
async def my_jobs(session: DbSession, user: CurrentUser) -> list[JobRead]:
    return await ser.jobs(session, await tools_svc.my_jobs(session, user))


@router.post("/uploads", response_model=ToolUploadRead, status_code=201, summary="工具上傳（暫存，不留存）")
async def upload(
    user: CurrentUser, file: UploadFile = File(...), data_type: str = Form(...), format: str | None = Form(None)
) -> ToolUploadRead:
    """檔案只存在 DATA_ROOT/tools/ 的暫存資料夾，沒有資料庫紀錄；建立任務時移進任務的 input（任務結束即刪），
    或逾時（UPLOAD_TTL）即刪。"""
    return await tools_svc.create(user, file, data_type, format)


@router.get("/uploads/{upload_id}", response_model=ToolUploadRead)
async def get_upload(upload_id: str, user: CurrentUser) -> ToolUploadRead:
    return tools_svc.get(upload_id, user)


@router.post("/uploads/{upload_id}/preview", response_model=PreviewRead, summary="抽樣套用步驟，即時回傳前後對照")
async def preview(upload_id: str, body: ToolPreviewBody, user: CurrentUser) -> PreviewRead:
    """前後對照樣本、每個步驟的警告（如「文字數字轉成數值」把類別欄整欄變成缺值）；TABULAR / TEXT 另附輸入樣本與
    整條管線輸出的每欄統計（型別、缺值、唯一值數、範圍、最常見的值）與列數。"""
    return await tools_svc.preview(
        upload_id,
        user,
        body.steps,
        sample=body.sample,
        spec=body.spec,
        task_type=body.task_type,
        thumb=body.thumb,
        image_ids=body.image_ids,
    )


@router.post("/uploads/{upload_id}/process", response_model=JobRead, status_code=202, summary="整檔前處理 → 任務")
async def process(upload_id: str, body: ToolProcessBody, session: DbSession, user: CurrentUser) -> JobRead:
    """建立 kind=preprocess 的任務（個人工作區、全域佇列）。完成後在任務頁下載 zip
    （processed.* + pipeline.json + summary.json）；下載一次即刪，或到期（工具預設的 result_ttl_hours）自動刪。"""
    job = await tools_svc.start_preprocess_job(
        session, upload_id, user, steps=body.steps, spec=body.spec, task_type=body.task_type, name=body.name
    )
    return await ser.job(session, job)


@router.post("/uploads/{upload_id}/analyze", response_model=JobRead, status_code=202, summary="資料分析 → 任務")
async def analyze(upload_id: str, body: ToolAnalyzeBody, session: DbSession, user: CurrentUser) -> JobRead:
    """kind=analysis：tabular_profile（相關性、共線性 VIF、對目標的解釋力、建議）或 image_quality
    （各群組的 IQA 指標、最會飄的指標、embedding 相似度）。報告存在任務結果，不保留原始資料。"""
    job = await tools_svc.start_analysis_job(
        session, upload_id, user, analysis=body.analysis, params=body.params, name=body.name
    )
    return await ser.job(session, job)


@router.delete("/uploads/{upload_id}", response_model=Ok, summary="立即刪除暫存檔")
async def delete(upload_id: str, user: CurrentUser) -> Ok:
    tools_svc.get(upload_id, user)
    tools_svc.remove(upload_id)
    return Ok()
