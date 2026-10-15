from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Query, UploadFile

from app.core.deps import AdminUser, DbSession, require_perm
from app.models import User
from app.routers import _serialize as ser
from app.schemas.admin import (
    AdminOverview,
    AuditLogRead,
    GpuResetBody,
    GpuResetResult,
    ModelZooEntry,
    NodeStatus,
    QueueRead,
    UsageHistory,
    ZooImportBody,
    ZooTask,
)
from app.schemas.common import Ok, Page
from app.schemas.job import JobRead, MoveBody, OrderBody, StopBody
from app.schemas.settings import JobDefaults, ResourcePool, ToolDefaults
from app.services import (
    audit as audit_svc,
)
from app.services import (
    gpu as gpu_svc,
)
from app.services import (
    jobs as jobs_svc,
)
from app.services import (
    model_zoo as zoo_svc,
)
from app.services import (
    node as node_svc,
)
from app.services import (
    project_requests as requests_svc,
)
from app.services import (
    settings as settings_svc,
)
from app.services import (
    usage as usage_svc,
)

router = APIRouter(prefix="/admin", tags=["admin"])

# Fine-grained permissions (see app/core/permissions.py): admins run the day-to-day operations, only superadmins
# touch resources, the model zoo and user roles.
PoolManager = Annotated[User, Depends(require_perm("pool.manage"))]
JobController = Annotated[User, Depends(require_perm("jobs.control"))]
ZooManager = Annotated[User, Depends(require_perm("model_zoo.manage"))]
GpuResetter = Annotated[User, Depends(require_perm("gpu.reset"))]


@router.get("/overview", response_model=AdminOverview)
async def overview(session: DbSession, _: AdminUser) -> AdminOverview:
    running, queued = await jobs_svc.queue(session)
    _, pending = await requests_svc.list_requests(
        session, applicant_id=None, statuses=["submitted", "in_review"], page=1, page_size=1
    )
    pool = await settings_svc.get_resource_pool(session)
    alloc = await node_svc.allocated(session)
    total = len(pool.gpu_indices)
    return AdminOverview(
        pending_requests=pending,
        queued=len(queued),
        running=len(running),
        pool_gpu_used=alloc.gpu,
        pool_gpu_total=total,
        pool_utilization=round(alloc.gpu / total * 100) if total else 0,
    )


@router.get("/node", response_model=NodeStatus, summary="實體節點：GPU、CPU、記憶體、磁碟")
async def node(session: DbSession, _: AdminUser) -> NodeStatus:
    return await node_svc.node_status(session)


@router.post("/gpus/{index}/reset", response_model=GpuResetResult, summary="強制釋放 GPU 顯存（superadmin）")
async def reset_gpu(index: int, body: GpuResetBody, session: DbSession, admin: GpuResetter) -> GpuResetResult:
    """jobs：強制中斷排程器放在這張 GPU 上的任務；all：再把驅動程式看到的其他程序一併 kill；
    device：再執行 GPU_RESET_COMMAND（nvidia-smi --gpu-reset）。一律寫入稽核紀錄。"""
    return await gpu_svc.reset(session, admin, index, body.mode, body.reason)


@router.get("/usage", response_model=UsageHistory, summary="資源使用率歷史（節點、資源池、各專案）")
async def usage(
    session: DbSession, _: AdminUser, range: str = Query("24h", pattern="^(1h|6h|24h|7d|30d)$")
) -> UsageHistory:
    """排程器每 USAGE_SAMPLE_INTERVAL_S 秒取樣一次；回傳依區間自動分桶的平均值，
    以及各專案在此區間的時間加權平均配置（相對配額 / 資源池 / 系統總量的百分比）。"""
    from app.core.config import get_settings

    return await usage_svc.history(session, range, get_settings().usage_sample_interval_s)


@router.get("/settings/resource-pool", response_model=ResourcePool)
async def get_pool(session: DbSession, _: AdminUser) -> ResourcePool:
    return await settings_svc.get_resource_pool(session)


@router.put("/settings/resource-pool", response_model=ResourcePool, summary="所有專案合計可用的總資源池")
async def put_pool(body: ResourcePool, session: DbSession, admin: PoolManager) -> ResourcePool:
    """superadmin only."""
    physical = node_svc.detect_gpus()
    if physical:
        bad = [i for i in body.gpu_indices if i not in {g.index for g in physical}]
        if bad:
            from app.core.errors import bad_request

            raise bad_request("GPU_NOT_PRESENT", f"實體沒有 GPU {bad}")
    return await settings_svc.set_resource_pool(session, body, admin.id)


@router.get("/settings/job-defaults", response_model=JobDefaults)
async def get_job_defaults(session: DbSession, _: AdminUser) -> JobDefaults:
    return await settings_svc.get_job_defaults(session)


@router.put("/settings/job-defaults", response_model=JobDefaults, summary="Job 預設值（superadmin）")
async def put_job_defaults(body: JobDefaults, session: DbSession, admin: PoolManager) -> JobDefaults:
    return await settings_svc.set_job_defaults(session, body, admin.id)


@router.get("/settings/tool-defaults", response_model=ToolDefaults, summary="個人工作區（工具任務）的預設配額")
async def get_tool_defaults(session: DbSession, _: AdminUser) -> ToolDefaults:
    return await settings_svc.get_tool_defaults(session)


@router.put("/settings/tool-defaults", response_model=ToolDefaults, summary="個人工作區預設配額（superadmin）")
async def put_tool_defaults(body: ToolDefaults, session: DbSession, admin: PoolManager) -> ToolDefaults:
    """影響之後建立的個人工作區；已存在的工作區在專案配額頁個別調整。"""
    return await settings_svc.set_tool_defaults(session, body, admin.id)


@router.get("/queue", response_model=QueueRead, summary="執行中 + 等待中（含等待原因）")
async def get_queue(session: DbSession, _: AdminUser) -> QueueRead:
    running, queued = await jobs_svc.queue(session)
    return QueueRead(running=await ser.jobs(session, running, with_queue=False), queued=await ser.jobs(session, queued))


@router.put("/queue/order", response_model=list[JobRead], summary="整批重排等待中的任務")
async def put_order(body: OrderBody, session: DbSession, admin: JobController) -> list[JobRead]:
    return await ser.jobs(session, await jobs_svc.set_order(session, admin, body.job_ids))


@router.post("/queue/{job_id}/move", response_model=list[JobRead])
async def move_job(job_id: int, body: MoveBody, session: DbSession, admin: JobController) -> list[JobRead]:
    return await ser.jobs(
        session, await jobs_svc.move(session, admin, await jobs_svc.get(session, job_id), body.position)
    )


@router.post("/jobs/{job_id}/stop", response_model=JobRead, summary="強制中斷（必填理由）")
async def stop_job(job_id: int, body: StopBody, session: DbSession, admin: JobController) -> JobRead:
    job = await jobs_svc.get(session, job_id)
    return await ser.job(session, await jobs_svc.cancel(session, admin, job, body.reason, forced=True))


@router.post("/jobs/{job_id}/restart", response_model=JobRead, status_code=202, summary="重新排入佇列（複製為新任務）")
async def restart_job(job_id: int, session: DbSession, admin: JobController) -> JobRead:
    """已結束（failed / cancelled / succeeded）的任務以相同輸入與設定重新建立一個新任務進入佇列。
    一次性上傳的輸入在任務結束時已刪除，這類任務無法重啟。"""
    job = await jobs_svc.get(session, job_id)
    return await ser.job(session, await jobs_svc.restart(session, admin, job))


@router.delete("/jobs/{job_id}", response_model=Ok, summary="刪除任務與其 log / 輸出")
async def delete_job(job_id: int, session: DbSession, admin: JobController) -> Ok:
    await jobs_svc.delete(session, admin, await jobs_svc.get(session, job_id))
    return Ok()


@router.get("/audit", response_model=Page[AuditLogRead])
async def audit(
    session: DbSession, _: AdminUser, page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200)
) -> Page[AuditLogRead]:
    rows, total = await audit_svc.list_recent(session, page_size, (page - 1) * page_size)
    return Page(items=[AuditLogRead.model_validate(r) for r in rows], total=total, page=page, page_size=page_size)


@router.get("/model-zoo", response_model=list[ModelZooEntry], summary="目錄需要的預訓練權重是否已在模型庫")
async def model_zoo(_: AdminUser, verify: bool = False) -> list[ModelZooEntry]:
    """`verify=true` 會重新計算每個檔案的 sha256（大檔案要幾秒）。"""
    return zoo_svc.status(verify=verify)


@router.get("/model-zoo/tasks", response_model=list[ZooTask], summary="背景匯入的進度")
async def model_zoo_tasks(_: AdminUser) -> list[ZooTask]:
    return zoo_svc.tasks()


@router.post("/model-zoo/{weight_id}/upload", response_model=ModelZooEntry, summary="從瀏覽器上傳權重檔")
async def model_zoo_upload(
    weight_id: str, session: DbSession, admin: ZooManager, file: UploadFile = File(...)
) -> ModelZooEntry:
    """單檔權重直接上傳；Hugging Face 類型請上傳整個 snapshot 資料夾的 zip / tar.gz。會比對目錄登記的 sha256。"""
    entry = await zoo_svc.upload(weight_id, file)
    await audit_svc.record(
        session, admin.id, "model_zoo.upload", "model_zoo", None, {"weight": weight_id, "file": file.filename}
    )
    await session.commit()
    return entry


@router.post(
    "/model-zoo/{weight_id}/import", response_model=ZooTask, status_code=202, summary="從內網 URL 或伺服器路徑匯入"
)
async def model_zoo_import(weight_id: str, body: ZooImportBody, session: DbSession, admin: ZooManager) -> ZooTask:
    """背景執行；進度看 `GET /admin/model-zoo/tasks`。
    URL 主機要在 MODEL_ZOO_ALLOWED_HOSTS，路徑要在 MODEL_ZOO_IMPORT_ROOT。"""
    task = await zoo_svc.start_import(weight_id, source=body.source, url=body.url, path=body.path)
    await audit_svc.record(
        session, admin.id, "model_zoo.import", "model_zoo", None, {"weight": weight_id, "source": task.source}
    )
    await session.commit()
    return task


@router.delete("/model-zoo/{weight_id}", response_model=Ok, summary="從模型庫移除權重")
async def model_zoo_delete(weight_id: str, session: DbSession, admin: ZooManager) -> Ok:
    zoo_svc.delete(weight_id)
    await audit_svc.record(session, admin.id, "model_zoo.delete", "model_zoo", None, {"weight": weight_id})
    await session.commit()
    return Ok()
