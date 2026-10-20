"""Deleting jobs: creators delete their own finished jobs, maintainers any in the project, admins everywhere
(bulk from the 任務管理 page). Artifacts go with the job unless another job still uses them."""

from __future__ import annotations

from app.core.config import get_settings
from app.db.session import get_sessionmaker
from app.models import Artifact, Job
from app.services import jobs as jobs_svc
from tests.test_ephemeral import _register_model
from tests.test_uploads_internal import _upload_and_job


async def _finish(job_id: int, status: str = "succeeded") -> None:
    async with get_sessionmaker()() as session:
        j = await jobs_svc.get(session, job_id)
        await jobs_svc.finish(session, j, status, error="x" if status == "failed" else None)


async def _inference(client, slug: str, artifact_id: int, headers: dict) -> dict:
    r = await client.post(
        f"/api/v1/projects/{slug}/jobs",
        json={
            "kind": "inference",
            "name": "run",
            "artifact_id": artifact_id,
            "config": {"mode": "predict"},
            "input": {"kind": "inline", "rows": [{"a": 1, "b": 2}], "spec": {}},
            "requested_cpu": 1,
            "requested_memory_mb": 512,
        },
        headers=headers,
    )
    assert r.status_code == 202, r.text
    return r.json()


async def test_creator_deletes_own_finished_job_with_its_artifacts(client, admin, user, other):
    _project, _up, job = await _upload_and_job(client, admin, user)
    # active → refused for everyone
    r = await client.delete(f"/api/v1/jobs/{job['id']}", headers=user)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "JOB_ACTIVE"
    model = await _register_model(client, job)
    await _finish(job["id"])
    model_file = get_settings().data_root / model["path"]
    assert model_file.exists()
    # another member (not the creator) may not; the creator may, and the artifact goes with the job
    r = await client.delete(f"/api/v1/jobs/{job['id']}", headers=other)
    assert r.status_code == 403 and r.json()["detail"]["code"] == "JOB_NOT_OWNER"
    r = await client.delete(f"/api/v1/jobs/{job['id']}", headers=user)
    assert r.status_code == 200, r.text
    assert not model_file.exists()
    async with get_sessionmaker()() as session:
        assert await session.get(Job, job["id"]) is None
        assert await session.get(Artifact, model["id"]) is None
    assert (await client.get(f"/api/v1/jobs/{job['id']}", headers=user)).status_code == 404
    audit = (await client.get("/api/v1/admin/audit", headers=admin)).json()["items"]
    assert audit[0]["action"] == "job.delete" and audit[0]["payload"]["artifacts"] == 1


async def test_model_in_use_blocks_the_training_job(client, admin, user, other):
    project, _up, job = await _upload_and_job(client, admin, user)
    model = await _register_model(client, job)
    await _finish(job["id"])
    inf = await _inference(client, project["slug"], model["id"], other)
    await _finish(inf["id"], "failed")
    r = await client.delete(f"/api/v1/jobs/{job['id']}", headers=user)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "ARTIFACT_IN_USE"
    # a maintainer may delete someone else's job; the creator of the inference run may delete it too
    r = await client.patch(
        f"/api/v1/projects/{project['slug']}/members/{(await client.get('/api/v1/me', headers=other)).json()['id']}",
        json={"role": "maintainer"},
        headers=user,
    )
    assert r.status_code == 200, r.text
    assert (await client.delete(f"/api/v1/jobs/{inf['id']}", headers=other)).status_code == 200
    assert (await client.delete(f"/api/v1/jobs/{job['id']}", headers=other)).status_code == 200


async def test_admin_lists_and_bulk_deletes(client, admin, user, other):
    project, _up, job = await _upload_and_job(client, admin, user)
    model = await _register_model(client, job)
    await _finish(job["id"])
    inf = await _inference(client, project["slug"], model["id"], other)
    assert (await client.get("/api/v1/admin/jobs", headers=user)).status_code == 403
    page = (await client.get("/api/v1/admin/jobs", headers=admin)).json()
    assert page["total"] == 2 and {j["id"] for j in page["items"]} == {job["id"], inf["id"]}
    assert page["items"][0]["project_slug"] == project["slug"]
    page = (await client.get("/api/v1/admin/jobs?kind=train&q=upload", headers=admin)).json()
    assert [j["id"] for j in page["items"]] == [job["id"]]
    page = (await client.get(f"/api/v1/admin/jobs?project={project['slug']}&status=queued", headers=admin)).json()
    assert [j["id"] for j in page["items"]] == [inf["id"]]
    assert (await client.get("/api/v1/admin/jobs?q=999", headers=admin)).json()["total"] == 0
    # bulk: the queued inference run is skipped (active), the training job is skipped (model still in use)
    r = await client.post("/api/v1/admin/jobs/delete", json={"job_ids": [job["id"], inf["id"], 4242]}, headers=admin)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["deleted"] == [] and {s["id"]: s["code"] for s in body["skipped"]} == {
        job["id"]: "ARTIFACT_IN_USE",
        inf["id"]: "JOB_ACTIVE",
        4242: "JOB_NOT_FOUND",
    }
    await _finish(inf["id"], "cancelled")
    r = await client.post("/api/v1/admin/jobs/delete", json={"job_ids": [inf["id"], job["id"]]}, headers=admin)
    assert r.json() == {"deleted": [inf["id"], job["id"]], "skipped": []}
    assert (await client.get("/api/v1/admin/jobs", headers=admin)).json()["total"] == 0
    assert (await client.post("/api/v1/admin/jobs/delete", json={"job_ids": [1]}, headers=user)).status_code == 403
    assert (await client.get(f"/api/v1/projects/{project['slug']}", headers=user)).json()["storage_used_bytes"] == 0
