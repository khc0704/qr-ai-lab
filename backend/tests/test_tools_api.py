"""Standalone tools: upload → real-time preview → the heavy part is a job in the personal workspace → download once."""

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


async def test_preview_is_real_time_and_process_becomes_a_workspace_job(client, user, other, admin):
    # first call creates the workspace (fresh instance must serialize with members / owner)
    ws = (await client.get("/api/v1/tools/workspace", headers=user)).json()
    assert ws["kind"] == "personal" and ws["members"][0]["user"]["username"] == "user"
    up = await _upload(client, user)
    uid = up["id"]
    assert up["format"] == "csv" and up["detected_spec"]["row_count"] == 4
    assert (await client.get(f"/api/v1/tools/uploads/{uid}", headers=other)).status_code == 404
    steps = [{"op": "tabular.impute", "params": {"strategy": "median"}}, {"op": "tabular.standardize"}]
    r = await client.post(
        f"/api/v1/tools/uploads/{uid}/preview", json={"steps": steps, "spec": {"target": "yield_pct"}}, headers=user
    )
    assert r.status_code == 200, r.text
    assert {s["column"]: s for s in r.json()["after"]["stats"]}["x1"]["missing"] == 0

    r = await client.post(
        f"/api/v1/tools/uploads/{uid}/process", json={"steps": steps, "spec": {"target": "yield_pct"}}, headers=user
    )
    assert r.status_code == 202, r.text
    job = r.json()
    assert job["kind"] == "preprocess" and job["status"] == "queued" and job["project_slug"] == "ws-user"
    assert job["input"]["tool"] is True and job["input"]["data_type"] == "TABULAR" and job["config"]["steps"] == steps
    # the upload was consumed (moved into the job input dir), nothing is left in tools/
    assert not get_storage().abs(f"tools/{uid}").exists()
    assert get_storage().job_input_dir(job["id"]).joinpath("data.csv").exists()
    # personal workspace: created on first use with the tool defaults, hidden from the normal project list
    ws = (await client.get("/api/v1/tools/workspace", headers=user)).json()
    assert ws["kind"] == "personal" and ws["cpu_limit"] == 2 and ws["members"][0]["role"] == "owner"
    assert [p["slug"] for p in (await client.get("/api/v1/projects", headers=user)).json()] == []
    assert "ws-user" in [
        p["slug"] for p in (await client.get("/api/v1/projects?include_personal=true", headers=user)).json()
    ]
    mine = (await client.get("/api/v1/tools/jobs", headers=user)).json()
    assert [j["id"] for j in mine] == [job["id"]]
    assert (await client.get(f"/api/v1/jobs/{job['id']}", headers=other)).status_code == 404

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
    # image analysis with DINO falls back to metrics when the workspace has no GPU quota
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
    # tool defaults are superadmin territory and shape new workspaces
    r = await client.put(
        "/api/v1/admin/settings/tool-defaults",
        json={
            "gpu_limit": 1,
            "cpu_limit": 4,
            "memory_limit_mb": 8192,
            "storage_quota_mb": 4096,
            "max_concurrent_jobs": 2,
            "result_ttl_hours": 48,
        },
        headers=superadmin,
    )
    assert r.status_code == 200 and r.json()["cpu_limit"] == 4
    assert (await client.get("/api/v1/admin/settings/tool-defaults", headers=user)).status_code == 403


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
