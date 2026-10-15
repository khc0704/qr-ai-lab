from __future__ import annotations

from fastapi import APIRouter, File, Query, UploadFile

from app.core.deps import AdminUser, DbSession
from app.routers import _serialize as ser
from app.schemas.admin import (
    AdminOverview,
    AuditLogRead,
    ModelZooEntry,
    NodeStatus,
    QueueRead,
    ZooImportBody,
    ZooTask,
)
from app.schemas.common import Ok, Page
from app.schemas.job import JobRead, MoveBody, OrderBody, StopBody
from app.schemas.settings import JobDefaults, ResourcePool
from app.services import (
    audit as audit_svc,
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

router = APIRouter(prefix="/admin", tags=["admin"])


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


@router.get("/settings/resource-pool", response_model=ResourcePool)
async def get_pool(session: DbSession, _: AdminUser) -> ResourcePool:
    return await settings_svc.get_resource_pool(session)


@router.put("/settings/resource-pool", response_model=ResourcePool, summary="所有專案合計可用的總資源池")
async def put_pool(body: ResourcePool, session: DbSession, admin: AdminUser) -> ResourcePool:
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


@router.put("/settings/job-defaults", response_model=JobDefaults)
async def put_job_defaults(body: JobDefaults, session: DbSession, admin: AdminUser) -> JobDefaults:
    return await settings_svc.set_job_defaults(session, body, admin.id)


@router.get("/queue", response_model=QueueRead, summary="執行中 + 等待中（含等待原因）")
async def get_queue(session: DbSession, _: AdminUser) -> QueueRead:
    running, queued = await jobs_svc.queue(session)
    return QueueRead(running=await ser.jobs(session, running, with_queue=False), queued=await ser.jobs(session, queued))


@router.put("/queue/order", response_model=list[JobRead], summary="整批重排等待中的任務")
async def put_order(body: OrderBody, session: DbSession, admin: AdminUser) -> list[JobRead]:
    return await ser.jobs(session, await jobs_svc.set_order(session, admin, body.job_ids))


@router.post("/queue/{job_id}/move", response_model=list[JobRead])
async def move_job(job_id: int, body: MoveBody, session: DbSession, admin: AdminUser) -> list[JobRead]:
    return await ser.jobs(
        session, await jobs_svc.move(session, admin, await jobs_svc.get(session, job_id), body.position)
    )


@router.post("/jobs/{job_id}/stop", response_model=JobRead, summary="強制中斷（必填理由）")
async def stop_job(job_id: int, body: StopBody, session: DbSession, admin: AdminUser) -> JobRead:
    job = await jobs_svc.get(session, job_id)
    return await ser.job(session, await jobs_svc.cancel(session, admin, job, body.reason, forced=True))


@router.delete("/jobs/{job_id}", response_model=Ok, summary="刪除任務與其 log / 輸出")
async def delete_job(job_id: int, session: DbSession, admin: AdminUser) -> Ok:
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
    weight_id: str, session: DbSession, admin: AdminUser, file: UploadFile = File(...)
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
async def model_zoo_import(weight_id: str, body: ZooImportBody, session: DbSession, admin: AdminUser) -> ZooTask:
    """背景執行；進度看 `GET /admin/model-zoo/tasks`。
    URL 主機要在 MODEL_ZOO_ALLOWED_HOSTS，路徑要在 MODEL_ZOO_IMPORT_ROOT。"""
    task = await zoo_svc.start_import(weight_id, source=body.source, url=body.url, path=body.path)
    await audit_svc.record(
        session, admin.id, "model_zoo.import", "model_zoo", None, {"weight": weight_id, "source": task.source}
    )
    await session.commit()
    return task


@router.delete("/model-zoo/{weight_id}", response_model=Ok, summary="從模型庫移除權重")
async def model_zoo_delete(weight_id: str, session: DbSession, admin: AdminUser) -> Ok:
    zoo_svc.delete(weight_id)
    await audit_svc.record(session, admin.id, "model_zoo.delete", "model_zoo", None, {"weight": weight_id})
    await session.commit()
    return Ok()
