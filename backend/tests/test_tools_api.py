"""Standalone tools: upload → real-time preview → the heavy part is a job in the shared tool pool → download once."""

from __future__ import annotations

import io
import json
import zipfile

from app.scheduler.loop import Scheduler
from app.storage.local import get_storage
from tests.test_scheduler import FakeRunner

CSV = b"x1,x2,yield_pct\n1.0,2.0,91.2\n,3.0,88.1\n3.0,,90.0\n50.0,1.0,70.0\n"


async def _upload(client, user, name=b"wat.csv", data=CSV, data_type="TABULAR"):
    r = await client.post(
        "/api/v1/tools/uploads",
        files={"file": (name.decode() if isinstance(name, bytes) else name, data, "application/octet-stream")},
        data={"data_type": data_type},
        headers=user,
    )
    assert r.status_code == 201, r.text
    return r.json()


async def test_preview_is_real_time_and_process_becomes_a_pool_job(client, user, other, admin):
    # first call creates the shared tool pool
    pool = (await client.get("/api/v1/tools/pool", headers=user)).json()
    assert pool["slug"] == "tools" and pool["my_active_jobs"] == 0 and pool["max_jobs_per_user"] == 2
    up = await _upload(client, user)
    uid = up["id"]
    assert up["format"] == "csv" and up["detected_spec"]["row_count"] == 4
    assert (await client.get(f"/api/v1/tools/uploads/{uid}", headers=other)).status_code == 404
    steps = [{"op": "tabular.impute", "params": {"strategy": "median"}}, {"op": "tabular.standardize"}]
    r = await client.post(
        f"/api/v1/tools/uploads/{uid}/preview", json={"steps": steps, "spec": {"target": "yield_pct"}}, headers=user
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert {s["column"]: s for s in body["after"]["stats"]}["x1"]["missing"] == 0
    # the typed response keeps the new per-step / per-column fields
    assert [s["op"] for s in body["step_details"]] == ["tabular.impute", "tabular.standardize"]
    assert body["step_details"][0]["warnings"] == [] and body["warnings"] == []
    assert body["rows_in"] == 4 and body["rows_out"] == 4
    cin = {c["name"]: c for c in body["columns_in"]}
    cout = {c["name"]: c for c in body["columns_out"]}
    assert cin["x1"]["dtype"] == "number" and cin["x1"]["missing"] >= 1 and cout["x1"]["missing"] == 0
    assert abs(cout["x1"]["mean"]) < 1e-6 and set(cin["x1"]) == {
        "name",
        "dtype",
        "missing",
        "missing_ratio",
        "unique",
        "min",
        "max",
        "mean",
        "top",
    }

    r = await client.post(
        f"/api/v1/tools/uploads/{uid}/process", json={"steps": steps, "spec": {"target": "yield_pct"}}, headers=user
    )
    assert r.status_code == 202, r.text
    job = r.json()
    assert job["kind"] == "preprocess" and job["status"] == "queued" and job["project_slug"] == "tools"
    assert job["input"]["tool"] is True and job["input"]["data_type"] == "TABULAR" and job["config"]["steps"] == steps
    # the upload was consumed (moved into the job input dir), nothing is left in tools/
    assert not get_storage().abs(f"tools/{uid}").exists()
    assert get_storage().job_input_dir(job["id"]).joinpath("data.csv").exists()
    # the tool pool is hidden from the project list; only the creator (and admins) see the job
    assert [p["slug"] for p in (await client.get("/api/v1/projects", headers=user)).json()] == []
    assert [p["slug"] for p in (await client.get("/api/v1/projects", headers=admin)).json()] == []
    assert (await client.get("/api/v1/projects/tools", headers=user)).status_code == 404
    assert (await client.get("/api/v1/tools/pool", headers=user)).json()["my_active_jobs"] == 1
    mine = (await client.get("/api/v1/tools/jobs", headers=user)).json()
    assert [j["id"] for j in mine] == [job["id"]]
    assert (await client.get("/api/v1/tools/jobs", headers=other)).json() == []
    assert (await client.get(f"/api/v1/jobs/{job['id']}", headers=other)).status_code == 404
    assert (await client.get(f"/api/v1/jobs/{job['id']}", headers=admin)).status_code == 200
    # per-user fairness: a second job is allowed, a third is not while two are still active
    up2 = await _upload(client, user)
    r = await client.post(f"/api/v1/tools/uploads/{up2['id']}/process", json={"steps": steps, "spec": {}}, headers=user)
    assert r.status_code == 202, r.text
    job2 = r.json()
    up3 = await _upload(client, user)
    r = await client.post(f"/api/v1/tools/uploads/{up3['id']}/process", json={"steps": steps, "spec": {}}, headers=user)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "TOOL_JOB_LIMIT"
    await client.delete(f"/api/v1/tools/uploads/{up3['id']}", headers=user)
    assert (await client.post(f"/api/v1/jobs/{job2['id']}/cancel", headers=user)).status_code == 200

    # the scheduler runs it like any job; the trainer gets the tool data type and the file name in the spec
    runner = FakeRunner()
    sched = Scheduler(runner=runner)
    sched.sampling = False
    await sched.tick()
    assert runner.started and runner.started[0].job_id == job["id"]
    from app.core.security import create_job_token

    tok = {"Authorization": f"Bearer {create_job_token(job['id'], 'preprocess', 600)}"}
    spec = (await client.get(f"/api/v1/internal/jobs/{job['id']}/spec", headers=tok)).json()
    assert spec["kind"] == "preprocess" and spec["data_type"] == "TABULAR" and spec["input"]["file"] == "data.csv"
    # pretend the trainer wrote the zip and reported the result
    out = get_storage().abs(job["output_path"]) / "output"
    out.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out / "preprocessed.zip", "w") as z:
        z.writestr("processed.csv", "x1,x2,yield_pct\n")
        z.writestr("pipeline.json", json.dumps({"steps": steps}))
    await client.post(
        f"/api/v1/internal/jobs/{job['id']}/result",
        json={"result": {"files": ["processed.csv", "pipeline.json"]}, "output_path": "output/preprocessed.zip"},
        headers=tok,
    )
    await client.post(f"/api/v1/internal/jobs/{job['id']}/status", json={"status": "succeeded"}, headers=tok)
    runner.finish(f"fake-{job['id']}", 0)
    await sched.tick()
    done = (await client.get(f"/api/v1/jobs/{job['id']}", headers=user)).json()
    assert done["status"] == "succeeded" and done["result"]["output_path"].endswith("preprocessed.zip")
    assert not get_storage().job_input_dir(job["id"]).exists()  # input deleted when the job ended

    # download hands the result over once
    r = await client.get(f"/api/v1/jobs/{job['id']}/download", headers=user)
    assert r.status_code == 200 and "wat-preprocessed.zip" in r.headers["content-disposition"]
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        assert {"processed.csv", "pipeline.json"} <= set(z.namelist())
    r = await client.get(f"/api/v1/jobs/{job['id']}/download", headers=user)
    assert r.status_code == 404 and "已下載" in r.json()["detail"]["message"]
    assert (await client.get(f"/api/v1/jobs/{job['id']}", headers=user)).json()["result"]["downloaded_at"]


async def test_analysis_job_and_validation(client, user, superadmin):
    up = await _upload(client, user)
    r = await client.post(
        f"/api/v1/tools/uploads/{up['id']}/analyze",
        json={"analysis": "image_quality", "params": {}},
        headers=user,
    )
    assert r.status_code == 400 and r.json()["detail"]["code"] == "ANALYSIS_DATA_TYPE"
    r = await client.post(
        f"/api/v1/tools/uploads/{up['id']}/analyze",
        json={"analysis": "tabular_profile", "params": {"target": "yield_pct"}},
        headers=user,
    )
    assert r.status_code == 202, r.text
    job = r.json()
    assert (
        job["kind"] == "analysis"
        and job["config"]["analysis"] == "tabular_profile"
        and job["config"]["target"] == "yield_pct"
    )
    # image analysis with DINO falls back to metrics when the tool pool has no GPU quota
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        from PIL import Image

        for g, base in (("a", 10), ("b", 200)):
            for i in range(2):
                b = io.BytesIO()
                Image.new("L", (32, 24), base + i).save(b, format="PNG")
                z.writestr(f"{g}/img{i}.png", b.getvalue())
    up = await _upload(client, user, name="imgs.zip", data=buf.getvalue(), data_type="IMAGE")
    r = await client.post(
        f"/api/v1/tools/uploads/{up['id']}/analyze",
        json={"analysis": "image_quality", "params": {"embedding": "dino"}},
        headers=user,
    )
    assert r.status_code == 202, r.text
    assert r.json()["requested_gpu"] == 0 and r.json()["config"]["embedding"] == "metrics"
    assert r.json()["config"]["backbone"] == "dinov2-small"
    up = await _upload(client, user, name="imgs2.zip", data=buf.getvalue(), data_type="IMAGE")
    r = await client.post(
        f"/api/v1/tools/uploads/{up['id']}/analyze",
        json={"analysis": "image_quality", "params": {"embedding": "dino", "backbone": "resnet50"}},
        headers=user,
    )
    assert r.status_code == 400 and r.json()["detail"]["code"] == "BAD_BACKBONE"
    # the tool pool quota is superadmin territory and flows into the shared project
    r = await client.put(
        "/api/v1/admin/settings/tool-pool",
        json={
            "gpu_limit": 1,
            "cpu_limit": 6,
            "memory_limit_mb": 8192,
            "storage_quota_mb": 4096,
            "max_concurrent_jobs": 2,
            "max_jobs_per_user": 1,
            "result_ttl_hours": 48,
        },
        headers=superadmin,
    )
    assert r.status_code == 200 and r.json()["cpu_limit"] == 6
    assert (await client.get("/api/v1/admin/settings/tool-pool", headers=user)).status_code == 403
    pool = (await client.get("/api/v1/tools/pool", headers=user)).json()
    assert pool["cpu_limit"] == 6 and pool["max_jobs_per_user"] == 1
    assert (await client.get("/api/v1/projects/tools", headers=superadmin)).json()["cpu_limit"] == 6


async def test_tool_pool_is_bounded_by_the_resource_pool(client, user, superadmin):
    # conftest pool: GPU [0, 1], 8 cores, 32 GB, 2 running jobs
    body = {
        "gpu_limit": 2,
        "cpu_limit": 9,
        "memory_limit_mb": 8192,
        "storage_quota_mb": 4096,
        "max_concurrent_jobs": 3,
        "max_jobs_per_user": 2,
        "result_ttl_hours": 24,
    }
    r = await client.put("/api/v1/admin/settings/tool-pool", json=body, headers=superadmin)
    assert r.status_code == 400 and r.json()["detail"]["code"] == "TOOL_POOL_EXCEEDS_POOL"
    assert "CPU 9" in r.json()["detail"]["message"] and "同時任務數 3" in r.json()["detail"]["message"]
    body.update(cpu_limit=8, max_concurrent_jobs=2)
    assert (await client.put("/api/v1/admin/settings/tool-pool", json=body, headers=superadmin)).status_code == 200
    # lowering the total pool shrinks the tool pool along with it (and the shared project's quota)
    r = await client.put(
        "/api/v1/admin/settings/resource-pool",
        json={"gpu_indices": [0], "cpu_cores": 4, "memory_mb": 16384, "max_running_jobs": 1, "allow_backfill": True},
        headers=superadmin,
    )
    assert r.status_code == 200, r.text
    tool = (await client.get("/api/v1/admin/settings/tool-pool", headers=superadmin)).json()
    assert (tool["gpu_limit"], tool["cpu_limit"], tool["memory_limit_mb"], tool["max_concurrent_jobs"]) == (
        1,
        4,
        8192,
        1,
    )
    assert tool["max_jobs_per_user"] == 2 and tool["result_ttl_hours"] == 24
    status = (await client.get("/api/v1/tools/pool", headers=user)).json()  # what the tools pages show
    assert status["cpu_limit"] == 4 and status["gpu_limit"] == 1 and status["max_concurrent_jobs"] == 1


async def test_tool_rejects_bad_type_and_deletes(client, user):
    r = await client.post(
        "/api/v1/tools/uploads", files={"file": ("wat.csv", CSV, "text/csv")}, data={"data_type": "IMAGE"}, headers=user
    )
    assert r.status_code == 400 and r.json()["detail"]["code"] == "UNKNOWN_FORMAT"
    r = await client.post(
        "/api/v1/tools/uploads", files={"file": ("wat.csv", CSV, "text/csv")}, data={"data_type": "NOPE"}, headers=user
    )
    assert r.status_code == 400 and r.json()["detail"]["code"] == "BAD_DATA_TYPE"
    up = await _upload(client, user)
    assert (await client.delete(f"/api/v1/tools/uploads/{up['id']}", headers=user)).status_code == 200
    assert not get_storage().abs(f"tools/{up['id']}").exists()
    assert (await client.get(f"/api/v1/tools/uploads/{up['id']}", headers=user)).status_code == 404
