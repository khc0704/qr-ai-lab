"""One-off (ephemeral) inference: server-chosen resources, hidden from the lists, no artifacts, expires."""

from __future__ import annotations

from datetime import timedelta

from app.core.config import get_settings
from app.core.security import create_job_token
from app.db.base import utcnow
from app.db.session import get_sessionmaker
from app.services import jobs as jobs_svc
from tests.test_uploads_internal import _upload_and_job


async def _register_model(client, job: dict) -> dict:
    """Walk the training job to running (scheduler + trainer protocol) and register a model artifact."""
    token = {"Authorization": f"Bearer {create_job_token(job['id'], 'train', 3600)}"}
    async with get_sessionmaker()() as session:
        await jobs_svc.mark_scheduled(session, await jobs_svc.get(session, job["id"]), [])
    r = await client.post(
        f"/api/v1/internal/jobs/{job['id']}/status", json={"status": "running", "stage": "training"}, headers=token
    )
    assert r.status_code == 200, r.text
    out = get_settings().data_root / job["output_path"] / "model"
    out.mkdir(parents=True, exist_ok=True)
    (out / "pipeline.joblib").write_bytes(b"x" * 1024)
    r = await client.post(
        f"/api/v1/internal/jobs/{job['id']}/artifacts",
        json={
            "name": "linear-yield",
            "kind": "model",
            "path": "model/pipeline.joblib",
            "framework": "sklearn",
            "metadata": {"task_type": "regression", "inference_modes": ["predict"]},
        },
        headers=token,
    )
    assert r.status_code == 201, r.text
    return r.json()


async def test_ephemeral_inference_lifecycle(client, admin, user):
    project, _up, train = await _upload_and_job(client, admin, user)
    slug = project["slug"]
    model = await _register_model(client, train)
    rows = [{"a": 1, "b": 2}, {"a": 3, "b": 6}]

    # only inference may be one-off
    r = await client.post(
        f"/api/v1/projects/{slug}/jobs",
        json={"kind": "train", "name": "x", "ephemeral": True, "input": {"kind": "upload", "upload_id": 1}},
        headers=user,
    )
    assert r.status_code == 400 and r.json()["detail"]["code"] == "EPHEMERAL_INFERENCE_ONLY"

    # the request names only the model, the mode and the rows: resources come from the server, clipped to quota
    r = await client.post(
        f"/api/v1/projects/{slug}/jobs",
        json={
            "kind": "inference",
            "name": "一次性推論",
            "ephemeral": True,
            "artifact_id": model["id"],
            "config": {"mode": "predict"},
            "input": {"kind": "inline", "spec": {}, "rows": rows},
        },
        headers=user,
    )
    assert r.status_code == 202, r.text
    job = r.json()
    assert job["ephemeral"] is True and job["requested_gpu"] == 0
    assert job["requested_cpu"] == min(2.0, float(project["cpu_limit"]))
    assert job["requested_memory_mb"] == min(4096, project["memory_limit_mb"])
    assert job["timeout_minutes"] <= 60

    # hidden from the regular lists, visible with ?ephemeral=true, flagged in the trainer spec
    listed = (await client.get(f"/api/v1/projects/{slug}/jobs", headers=user)).json()
    assert job["id"] not in [j["id"] for j in listed["items"]]
    only = (await client.get(f"/api/v1/projects/{slug}/jobs?ephemeral=true", headers=user)).json()
    assert [j["id"] for j in only["items"]] == [job["id"]]
    recent = (await client.get("/api/v1/jobs", headers=user)).json()
    assert job["id"] not in [j["id"] for j in recent]
    token = {"Authorization": f"Bearer {create_job_token(job['id'], 'inference', 3600)}"}
    spec = (await client.get(f"/api/v1/internal/jobs/{job['id']}/spec", headers=token)).json()
    assert spec["ephemeral"] is True and spec["artifact"]["id"] == model["id"]

    # once finished and older than the TTL the run disappears with its outputs
    root = get_settings().data_root
    out = root / job["output_path"] / "output"
    out.mkdir(parents=True, exist_ok=True)
    (out / "predictions.csv").write_text("id,prediction\n0,1\n", encoding="utf-8")
    async with get_sessionmaker()() as session:
        j = await jobs_svc.get(session, job["id"])
        j.status, j.finished_at = "succeeded", utcnow() - timedelta(hours=30)
        await session.commit()
    async with get_sessionmaker()() as session:
        assert await jobs_svc.expire_ephemeral_jobs(session, ttl_hours=48) == 0  # still within the TTL
        assert await jobs_svc.expire_ephemeral_jobs(session, ttl_hours=24) == 1
    assert (await client.get(f"/api/v1/jobs/{job['id']}", headers=user)).status_code == 404
    assert not (root / job["output_path"]).exists()
    # the regular training job is untouched
    assert (await client.get(f"/api/v1/jobs/{train['id']}", headers=user)).status_code == 200
