"""Standalone data tools (no project needed): preprocess a file and download the result. Nothing is kept."""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, File, Form, UploadFile
from fastapi.responses import FileResponse

from app.core.deps import CurrentUser
from app.schemas.common import Ok
from app.schemas.tools import ToolPreviewBody, ToolProcessBody, ToolProcessResult, ToolUploadRead
from app.services import tools as tools_svc

router = APIRouter(prefix="/tools", tags=["tools"])


@router.post("/uploads", response_model=ToolUploadRead, status_code=201, summary="前處理工具：上傳檔案（暫存，不留存）")
async def upload(
    user: CurrentUser, file: UploadFile = File(...), data_type: str = Form(...), format: str | None = Form(None)
) -> ToolUploadRead:
    """檔案只存在 DATA_ROOT/tools/ 的暫存資料夾，沒有資料庫紀錄；下載結果、按刪除或逾時（UPLOAD_TTL）即刪。"""
    return await tools_svc.create(user, file, data_type, format)


@router.get("/uploads/{upload_id}", response_model=ToolUploadRead)
async def get_upload(upload_id: str, user: CurrentUser) -> ToolUploadRead:
    return tools_svc.get(upload_id, user)


@router.post("/uploads/{upload_id}/preview", summary="抽樣套用步驟，回傳前後對照")
async def preview(upload_id: str, body: ToolPreviewBody, user: CurrentUser) -> dict:
    return await tools_svc.preview(
        upload_id, user, body.steps, sample=body.sample, spec=body.spec, task_type=body.task_type
    )


@router.post("/uploads/{upload_id}/process", response_model=ToolProcessResult, summary="對整個檔案執行步驟並打包")
async def process(upload_id: str, body: ToolProcessBody, user: CurrentUser) -> ToolProcessResult:
    """同步執行（受 TOOL_PROCESS_TIMEOUT_S 限制），完成後回傳摘要與下載路徑；zip 內含處理後資料、
    pipeline.json（可重播的步驟與狀態）與 summary.json。"""
    return await tools_svc.process(upload_id, user, body.steps, spec=body.spec, task_type=body.task_type)


@router.get("/uploads/{upload_id}/download", summary="下載結果 zip（下載後即刪除整個暫存資料夾）")
async def download(upload_id: str, user: CurrentUser, background: BackgroundTasks) -> FileResponse:
    zip_path, filename = tools_svc.result_file(upload_id, user)
    background.add_task(tools_svc.remove, upload_id)
    return FileResponse(zip_path, media_type="application/zip", filename=filename)


@router.delete("/uploads/{upload_id}", response_model=Ok, summary="立即刪除暫存檔")
async def delete(upload_id: str, user: CurrentUser) -> Ok:
    tools_svc.get(upload_id, user)
    tools_svc.remove(upload_id)
    return Ok()
