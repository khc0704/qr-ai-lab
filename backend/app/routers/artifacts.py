from __future__ import annotations

import asyncio
import os
import tempfile
import zipfile
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from app.core.deps import CurrentUser, DbSession, project_access
from app.core.errors import not_found
from app.schemas.artifact import ArtifactRead, ArtifactUpdate
from app.schemas.common import Ok
from app.services import artifacts as artifacts_svc
from app.services import projects as projects_svc
from app.storage.local import get_storage

router = APIRouter(prefix="/artifacts", tags=["artifacts"])


async def _access(artifact_id: int, session: DbSession, user: CurrentUser, min_role: str):
    art = await artifacts_svc.get(session, artifact_id)
    project = await projects_svc.get(session, art.project_id)
    access = await project_access(min_role)(session, user, project.slug)
    return art, access


@router.get("/{artifact_id}", response_model=ArtifactRead)
async def get_artifact(artifact_id: int, session: DbSession, user: CurrentUser) -> ArtifactRead:
    art, _ = await _access(artifact_id, session, user, "viewer")
    return ArtifactRead.model_validate(art)


@router.patch("/{artifact_id}", response_model=ArtifactRead, summary="設為 / 取消預設模型")
async def update_artifact(
    artifact_id: int, body: ArtifactUpdate, session: DbSession, user: CurrentUser
) -> ArtifactRead:
    art, access = await _access(artifact_id, session, user, "member")
    return ArtifactRead.model_validate(await artifacts_svc.set_default(session, access.user, art, body.is_default))


@router.get("/{artifact_id}/download")
async def download_artifact(artifact_id: int, session: DbSession, user: CurrentUser) -> FileResponse:
    art, _ = await _access(artifact_id, session, user, "viewer")
    path = get_storage().abs(art.path)
    if path.is_dir():  # model folders are zipped on the fly
        fd, tmp_name = tempfile.mkstemp(suffix=".zip")
        os.close(fd)
        await asyncio.to_thread(_zip_dir, path, Path(tmp_name))
        name = f"{art.name}-v{art.version}.zip"
        return FileResponse(tmp_name, filename=name, background=BackgroundTask(os.unlink, tmp_name))
    if not path.is_file():
        raise not_found("ARTIFACT_FILE_MISSING", "檔案不存在")
    return FileResponse(path, filename=path.name)


def _zip_dir(src: Path, dst: Path) -> None:
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(p for p in src.rglob("*") if p.is_file()):
            z.write(f, f.relative_to(src).as_posix())


@router.delete("/{artifact_id}", response_model=Ok)
async def delete_artifact(artifact_id: int, session: DbSession, user: CurrentUser) -> Ok:
    art, access = await _access(artifact_id, session, user, "maintainer")
    await artifacts_svc.delete(session, access.user, art)
    return Ok()
