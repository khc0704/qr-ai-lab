"""Real end-to-end: FastAPI served by uvicorn in-process → scheduler with SubprocessRunner → the actual trainer
package (sklearn families) in a child process → artifacts registered → inference job with inline rows.

Needs the trainer checkout next to backend/ (TRAINER_DIR) with its venv or an interpreter that has sklearn.
"""

from __future__ import annotations

import asyncio
import io
import random
import socket
import time

import pytest
import uvicorn

from app.core.config import get_settings
from app.main import create_app
from app.scheduler.loop import Scheduler
from app.scheduler.runner import SubprocessRunner
from app.storage.local import get_storage
from tests.conftest import make_project

pytestmark = pytest.mark.e2e


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _csv(n: int = 300) -> bytes:
    rng = random.Random(0)
    buf = io.StringIO()
    buf.write("x1,x2,yield_pct\n")
    for _ in range(n):
        x1, x2 = rng.gauss(0, 1), rng.gauss(0, 1)
        buf.write(f"{x1:.4f},{x2:.4f},{90 + 2 * x1 - x2 + rng.gauss(0, 0.2):.4f}\n")
    return buf.getvalue().encode()


async def _wait_terminal(client, job_id: int, headers: dict, sched: Scheduler, timeout: float = 120) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        await sched.tick()
        job = (await client.get(f"/api/v1/jobs/{job_id}", headers=headers)).json()
        if job["status"] in ("succeeded", "failed", "cancelled"):
            return job
        await asyncio.sleep(0.5)
    raise AssertionError(f"job {job_id} did not finish in {timeout}s")


async def test_train_and_infer_through_real_trainer(client, admin, user, superadmin):
    settings = get_settings()
    trainer_dir = settings.trainer_dir.resolve()
    if not (trainer_dir / "trainer" / "runtime.py").exists():
        pytest.skip("trainer checkout not found")
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(create_app(), host="127.0.0.1", port=port, log_level="warning"))
    serve_task = asyncio.create_task(server.serve())
    try:
        while not server.started:
            await asyncio.sleep(0.05)
        settings = settings.model_copy(update={"internal_backend_url": f"http://127.0.0.1:{port}"})
        sched = Scheduler(runner=SubprocessRunner(trainer_dir), settings=settings)

        project = await make_project(client, admin, user)
        slug = project["slug"]
        await client.patch(
            f"/api/v1/projects/{slug}/quota",
            json={"gpu_limit": 0, "cpu_limit": 4, "memory_limit_mb": 8192, "max_concurrent_jobs": 1},
            headers=superadmin,
        )
        up = await client.post(
            f"/api/v1/projects/{slug}/uploads",
            files={"file": ("yield.csv", _csv(), "text/csv")},
            data={"format": "csv"},
            headers=user,
        )
        assert up.status_code == 201, up.text
        upload = up.json()
        assert upload["detected_spec"]["row_count"] == 300

        r = await client.post(
            f"/api/v1/projects/{slug}/jobs",
            json={
                "kind": "train",
                "name": "e2e-automl",
                "task_type": "regression",
                "input": {"kind": "upload", "upload_id": upload["id"], "spec": {"target": "yield_pct"}},
                "config": {"search": {"max_trials": 3, "candidates": ["tabular.linear", "tabular.random_forest"]}},
                "requested_gpu": 0,
                "requested_cpu": 2,
                "requested_memory_mb": 2048,
            },
            headers=user,
        )
        assert r.status_code == 202, r.text
        train = r.json()
        assert get_storage().job_input_dir(train["id"]).exists()

        job = await _wait_terminal(client, train["id"], user, sched)
        logs = "\n".join((await client.get(f"/api/v1/jobs/{job['id']}/logs", headers=user)).json()["lines"])
        assert job["status"] == "succeeded", (job["error_message"], logs[-3000:])
        assert job["model_family"] in ("tabular.linear", "tabular.random_forest")
        assert job["metrics"]["leaderboard"] and len(job["metrics"]["leaderboard"]) == 3
        assert job["result"]["n_trials"] == 3 and job["result"]["metrics"]["rmse"] < 1.0
        assert "trial 1/3" in logs and "[SYSTEM]" in logs and "done" in logs
        assert not get_storage().job_input_dir(train["id"]).exists(), "uploaded data must be deleted after the job"
        arts = (await client.get(f"/api/v1/jobs/{job['id']}/artifacts", headers=user)).json()
        kinds = {a["kind"] for a in arts}
        assert {"model", "metrics"} <= kinds
        model = next(a for a in arts if a["kind"] == "model")
        assert model["is_default"] and model["model_family"] == job["model_family"]
        proj = (await client.get(f"/api/v1/projects/{slug}", headers=user)).json()
        assert proj["storage_used_bytes"] > 0
        listed = (await client.get(f"/api/v1/projects/{slug}/artifacts?kind=model", headers=user)).json()
        assert [a["id"] for a in listed if a["is_default"]] == [model["id"]]
        zipped = await client.get(f"/api/v1/artifacts/{model['id']}/download", headers=user)
        assert zipped.status_code == 200 and zipped.headers["content-type"].startswith("application/zip")

        r = await client.post(
            f"/api/v1/projects/{slug}/jobs",
            json={
                "kind": "inference",
                "name": "e2e-predict",
                "artifact_id": model["id"],
                "input": {"kind": "inline", "spec": {}, "rows": [{"x1": 1.0, "x2": 0.0}, {"x1": -1.0, "x2": 0.0}]},
                "requested_gpu": 0,
                "requested_cpu": 1,
                "requested_memory_mb": 1024,
            },
            headers=user,
        )
        assert r.status_code == 202, r.text
        infer = await _wait_terminal(client, r.json()["id"], user, sched)
        assert infer["status"] == "succeeded", infer["error_message"]
        preview = infer["result"]["preview"]
        assert len(preview) == 2 and preview[0]["prediction"] > preview[1]["prediction"]
        assert infer["result"]["output_path"].endswith("output/predictions.csv")
        reports = (await client.get(f"/api/v1/jobs/{infer['id']}/artifacts", headers=user)).json()
        assert reports and reports[0]["kind"] == "report"
        dl = await client.get(f"/api/v1/artifacts/{reports[0]['id']}/download", headers=user)
        assert dl.status_code == 200 and b"prediction" in dl.content
    finally:
        server.should_exit = True
        await serve_task
