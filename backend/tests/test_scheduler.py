"""Scheduler ticks against a fake runner: launch order, env (token + decrypted creds), log pump, finish,
input cleanup, cancel of a running job, timeout."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from pathlib import Path

from app.core.config import get_settings
from app.db.base import utcnow
from app.db.session import get_sessionmaker
from app.models import Job
from app.scheduler.loop import Scheduler
from app.scheduler.runner import LaunchSpec, RunState
from app.storage.local import get_storage
from tests.conftest import make_data_source, make_project


class FakeRunner:
    """Pretends to run jobs; trainer output is appended to the job log file the way a real child would."""

    kind = "fake"

    def __init__(self) -> None:
        from app.scheduler.runner import Enforcement

        self.enforcement = Enforcement(memory=True, cpu=True, cpuset=True)
        self.started: list[LaunchSpec] = []
        self.states: dict[str, RunState] = {}
        self.log_paths: dict[str, Path] = {}
        self.stopped: list[str] = []
        self.removed: list[str] = []

    async def start(self, spec: LaunchSpec) -> str:
        handle = f"fake-{spec.job_id}"
        self.started.append(spec)
        self.states[handle] = RunState(True, None)
        self.log_paths[handle] = spec.log_path
        return handle

    async def inspect(self, handle: str) -> RunState:
        return self.states.get(handle, RunState(False, None))

    async def stop(self, handle: str, grace: int = 10) -> None:
        self.stopped.append(handle)
        self.finish(handle, 143)

    async def find(self, job_id: int, handle: str | None) -> str | None:
        return None

    async def remove(self, handle: str) -> None:
        self.removed.append(handle)

    def pids(self, handle: str) -> list[int]:
        return []

    def emit(self, handle: str, line: str) -> None:
        with self.log_paths[handle].open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    def finish(self, handle: str, code: int) -> None:
        self.states[handle] = RunState(False, code)


async def _set_started_at(job_id: int, when) -> None:
    async with get_sessionmaker()() as s:
        job = await s.get(Job, job_id)
        job.started_at = when
        await s.commit()


async def test_tick_launches_pumps_logs_and_finishes(client, admin, user):
    project = await make_project(client, admin, user)
    slug = project["slug"]
    await client.patch(
        f"/api/v1/projects/{slug}/quota",
        json={"gpu_limit": 0, "cpu_limit": 8, "memory_limit_mb": 16384, "max_concurrent_jobs": 2},
        headers=admin,
    )
    ds = await make_data_source(client, user, slug)
    base = {
        "kind": "train",
        "mode": "manual",
        "model_family": "tabular.linear",
        "input": {"kind": "data_source", "data_source_id": ds["id"], "spec": {"target": "yield_pct"}},
        "requested_gpu": 0,
        "requested_cpu": 2,
        "requested_memory_mb": 2048,
    }
    j1 = (await client.post(f"/api/v1/projects/{slug}/jobs", json={**base, "name": "first"}, headers=user)).json()
    j2 = (await client.post(f"/api/v1/projects/{slug}/jobs", json={**base, "name": "second"}, headers=user)).json()

    runner = FakeRunner()
    sched = Scheduler(runner=runner, settings=get_settings())
    await sched.tick()
    # one launch per project per tick
    assert [s.job_id for s in runner.started] == [j1["id"]]
    spec = runner.started[0]
    assert spec.env["JOB_ID"] == str(j1["id"]) and spec.cpu == 2 and spec.memory_mb == 2048
    assert spec.env["DATA_SOURCE_KIND"] == "url" and spec.env["DATA_SOURCE_URL"] == "https://example.com/yield.csv"
    assert "Bearer x" in spec.env["DATA_SOURCE_HEADERS"]  # decrypted only here, for the job process
    assert get_storage().job_input_dir(j1["id"]).exists()
    r1 = (await client.get(f"/api/v1/jobs/{j1['id']}", headers=user)).json()
    assert r1["status"] == "running" and r1["assigned_gpus"] == []
    q = (await client.get("/api/v1/admin/queue", headers=admin)).json()
    assert [j["id"] for j in q["running"]] == [j1["id"]] and [j["id"] for j in q["queued"]] == [j2["id"]]

    # second tick launches the second job (quota: 2 concurrent)
    await sched.tick()
    assert [s.job_id for s in runner.started] == [j1["id"], j2["id"]]

    # trainer output is pumped into the log file and the event bus
    handle = f"fake-{j1['id']}"
    runner.emit(handle, "[INFO] hello from trainer")
    runner.emit(handle, "[WARN] careful")
    runner.emit(handle, "plain line")
    await asyncio.sleep(0.05)
    logs = (await client.get(f"/api/v1/jobs/{j1['id']}/logs", headers=user)).json()
    text = "\n".join(logs["lines"])
    assert "scheduled: gpu=[]" in text and "[INFO] hello from trainer" in text and "[WARN] careful" in text

    # trainer reports success through the internal API with its per-job token, then the process exits 0
    token = {"Authorization": f"Bearer {spec.env['JOB_TOKEN']}"}
    assert (await client.get(f"/api/v1/internal/jobs/{j1['id']}/spec", headers=token)).json()[
        "model_family"
    ] == "tabular.linear"
    assert (
        await client.post(f"/api/v1/internal/jobs/{j1['id']}/status", json={"status": "succeeded"}, headers=token)
    ).status_code == 200
    runner.finish(handle, 0)
    await sched.tick()
    r1 = (await client.get(f"/api/v1/jobs/{j1['id']}", headers=user)).json()
    assert r1["status"] == "succeeded" and r1["finished_at"]
    assert not get_storage().job_input_dir(j1["id"]).exists(), "user input must be deleted when the job ends"
    assert handle in runner.removed and j1["id"] not in sched.active

    # a running job that exits non-zero without a verdict fails with the log tail as the error
    h2 = f"fake-{j2['id']}"
    runner.emit(h2, "[ERROR] boom")
    await asyncio.sleep(0.05)
    runner.finish(h2, 1)
    await sched.tick()
    r2 = (await client.get(f"/api/v1/jobs/{j2['id']}", headers=user)).json()
    assert r2["status"] == "failed" and "exit code 1" in r2["error_message"]


async def test_cancel_and_timeout_of_running_jobs(client, admin, user):
    project = await make_project(client, admin, user)
    slug = project["slug"]
    await client.patch(
        f"/api/v1/projects/{slug}/quota",
        json={"gpu_limit": 0, "cpu_limit": 8, "memory_limit_mb": 16384, "max_concurrent_jobs": 2},
        headers=admin,
    )
    ds = await make_data_source(client, user, slug)
    base = {
        "kind": "train",
        "mode": "manual",
        "model_family": "tabular.linear",
        "input": {"kind": "data_source", "data_source_id": ds["id"], "spec": {"target": "yield_pct"}},
        "requested_gpu": 0,
        "requested_cpu": 1,
        "requested_memory_mb": 1024,
        "timeout_minutes": 1,
    }
    j1 = (await client.post(f"/api/v1/projects/{slug}/jobs", json={**base, "name": "to-cancel"}, headers=user)).json()
    j2 = (await client.post(f"/api/v1/projects/{slug}/jobs", json={**base, "name": "to-timeout"}, headers=user)).json()
    runner = FakeRunner()
    sched = Scheduler(runner=runner, settings=get_settings())
    await sched.tick()
    await sched.tick()
    assert len(runner.started) == 2

    # admin force-stop of a running job: cancel_requested → stop → cancelled
    r = await client.post(f"/api/v1/admin/jobs/{j1['id']}/stop", json={"reason": "資源讓給上線"}, headers=admin)
    assert r.json()["status"] == "running" and r.json()["cancel_reason"] == "資源讓給上線"
    await sched.tick()
    assert f"fake-{j1['id']}" in runner.stopped
    await sched.tick()
    r1 = (await client.get(f"/api/v1/jobs/{j1['id']}", headers=user)).json()
    assert r1["status"] == "cancelled" and r1["cancel_requested_by"]["username"] == "admin"
    audit = (await client.get("/api/v1/admin/audit", headers=admin)).json()["items"]
    assert {"job.stop", "job.cancelled"} <= {a["action"] for a in audit}

    # timeout: started 5 minutes ago with a 1 minute budget
    await _set_started_at(j2["id"], utcnow() - timedelta(minutes=5))
    await sched.tick()
    assert f"fake-{j2['id']}" in runner.stopped
    await sched.tick()
    r2 = (await client.get(f"/api/v1/jobs/{j2['id']}", headers=user)).json()
    assert r2["status"] == "failed" and "timeout" in r2["error_message"]
    text = "\n".join((await client.get(f"/api/v1/jobs/{j2['id']}/logs", headers=user)).json()["lines"])
    assert "timeout after 1 minutes" in text
