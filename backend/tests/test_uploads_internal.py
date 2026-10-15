from __future__ import annotations

from pathlib import Path

from app.core.config import get_settings
from app.core.security import create_job_token
from app.db.session import get_sessionmaker
from app.services import jobs as jobs_svc
from tests.conftest import make_project

CSV = "a,b,yield_pct\n" + "\n".join(f"{i},{i * 2},{0.9 + i / 1000}" for i in range(50)) + "\n"


async def _upload_and_job(client, admin, user):
    project = await make_project(client, admin, user)
    r = await client.post(
        f"/api/v1/projects/{project['slug']}/uploads", files={"file": ("train.csv", CSV, "text/csv")}, headers=user
    )
    assert r.status_code == 201, r.text
    up = r.json()
    assert (
        up["format"] == "csv"
        and up["detected_spec"]["row_count"] == 50
        and up["detected_spec"]["columns"] == ["a", "b", "yield_pct"]
    )
    r = await client.post(
        f"/api/v1/projects/{project['slug']}/jobs",
        json={
            "kind": "train",
            "name": "upload-run",
            "mode": "manual",
            "model_family": "tabular.linear",
            "input": {"kind": "upload", "upload_id": up["id"], "spec": {"target": "yield_pct"}},
            "requested_cpu": 1,
            "requested_memory_mb": 1024,
        },
        headers=user,
    )
    assert r.status_code == 202, r.text
    return project, up, r.json()


async def test_upload_claimed_into_job_input(client, admin, user):
    project, up, job = await _upload_and_job(client, admin, user)
    assert job["input"]["original_filename"] == "train.csv" and job["input"]["spec"]["row_count"] == 50
    root = get_settings().data_root
    assert (root / "jobs" / str(job["id"]) / "input" / "data.csv").exists()
    assert not (root / "uploads" / str(up["id"])).exists()
    # a claimed upload cannot be reused
    r = await client.post(
        f"/api/v1/projects/{project['slug']}/jobs",
        json={
            "kind": "train",
            "name": "again",
            "mode": "manual",
            "model_family": "tabular.linear",
            "input": {"kind": "upload", "upload_id": up["id"]},
        },
        headers=user,
    )
    assert r.status_code == 409


async def test_internal_protocol(client, admin, user, superadmin):
    project, _up, job = await _upload_and_job(client, admin, user)
    token = {"Authorization": f"Bearer {create_job_token(job['id'], 'train', 3600)}"}
    wrong = {"Authorization": f"Bearer {create_job_token(job['id'] + 99, 'train', 3600)}"}
    assert (await client.get(f"/api/v1/internal/jobs/{job['id']}/spec", headers=wrong)).status_code == 403
    assert (await client.get(f"/api/v1/internal/jobs/{job['id']}/spec", headers=user)).status_code == 401

    spec = (await client.get(f"/api/v1/internal/jobs/{job['id']}/spec", headers=token)).json()
    assert (
        spec["model_family"] == "tabular.linear"
        and spec["data_type"] == "TABULAR"
        and spec["input"]["file"] == "data.csv"
    )

    # scheduler marks scheduled, trainer reports running + metrics + leaderboard
    async with get_sessionmaker()() as session:
        j = await jobs_svc.get(session, job["id"])
        await jobs_svc.mark_scheduled(session, j, [])
    assert (
        await client.post(
            f"/api/v1/internal/jobs/{job['id']}/status",
            json={"status": "running", "stage": "training", "progress": 10},
            headers=token,
        )
    ).status_code == 200
    assert (await client.get(f"/api/v1/jobs/{job['id']}", headers=user)).json()["status"] == "running"
    for trial, m in ((1, 0.08), (2, 0.05)):
        await client.post(
            f"/api/v1/internal/jobs/{job['id']}/metrics",
            json={
                "trial": trial,
                "metrics": {"rmse": m},
                "leaderboard_row": {"trial": trial, "family": "tabular.linear", "metric": m, "params": {}},
            },
            headers=token,
        )
    j = (await client.get(f"/api/v1/jobs/{job['id']}", headers=user)).json()
    assert j["metrics"]["rmse"] == 0.05 and [r["trial"] for r in j["metrics"]["leaderboard"]] == [
        2,
        1,
    ]  # regression → minimize

    # artifact registration: file must exist under the job output dir; first model becomes default
    out = get_settings().data_root / job["output_path"] / "model"
    out.mkdir(parents=True, exist_ok=True)
    (out / "pipeline.joblib").write_bytes(b"x" * 2048)
    r = await client.post(
        f"/api/v1/internal/jobs/{job['id']}/artifacts",
        json={
            "name": "linear-yield",
            "kind": "model",
            "path": "model/pipeline.joblib",
            "framework": "sklearn",
            "metrics": {"rmse": 0.05},
            "metadata": {"task_type": "regression"},
        },
        headers=token,
    )
    assert r.status_code == 201, r.text
    art = r.json()
    assert art["is_default"] is True and art["size_bytes"] == 2048 and art["version"] == 1
    assert (
        await client.post(
            f"/api/v1/internal/jobs/{job['id']}/artifacts",
            json={"name": "nope", "kind": "report", "path": "report/missing.png", "framework": "sklearn"},
            headers=token,
        )
    ).status_code == 404
    assert (await client.get(f"/api/v1/projects/{project['slug']}", headers=user)).json()["storage_used_bytes"] >= 2048
    assert (await client.get(f"/api/v1/jobs/{job['id']}/artifacts", headers=user)).json()[0]["name"] == "linear-yield"

    # storage quota: a 1024 MB quota cannot be exceeded with small files; the check path is exercised by the service
    (out / "big.bin").write_bytes(b"y" * 4096)
    await client.patch(f"/api/v1/projects/{project['slug']}/quota", json={"storage_quota_mb": 1024}, headers=superadmin)
    r = await client.post(
        f"/api/v1/internal/jobs/{job['id']}/artifacts",
        json={"name": "big", "kind": "report", "path": "model/big.bin", "framework": "sklearn"},
        headers=token,
    )
    assert r.status_code == 201  # 6 KB < 1024 MB
    assert (
        await client.post(f"/api/v1/internal/jobs/{job['id']}/result", json={"result": {"rows": 3}}, headers=token)
    ).status_code == 200

    # finishing removes the input dir and keeps artifacts
    async with get_sessionmaker()() as session:
        j2 = await jobs_svc.get(session, job["id"])
        await jobs_svc.finish(session, j2, "succeeded")
    assert not (get_settings().data_root / "jobs" / str(job["id"])).exists()
    assert Path(get_settings().data_root / art["path"]).exists()
    final = (await client.get(f"/api/v1/jobs/{job['id']}", headers=user)).json()
    assert final["status"] == "succeeded" and final["result"]["rows"] == 3

    # inference job referencing the default model; inline rows
    r = await client.post(
        f"/api/v1/projects/{project['slug']}/jobs",
        json={
            "kind": "inference",
            "name": "infer-1",
            "artifact_id": art["id"],
            "input": {"kind": "inline", "rows": [{"a": 1, "b": 2}]},
            "requested_cpu": 1,
            "requested_memory_mb": 1024,
        },
        headers=user,
    )
    assert r.status_code == 202, r.text
    assert r.json()["model_family"] == "tabular.linear" and r.json()["task_type"] == "regression"
    # model in use → cannot delete
    assert (await client.delete(f"/api/v1/artifacts/{art['id']}", headers=user)).status_code == 409
